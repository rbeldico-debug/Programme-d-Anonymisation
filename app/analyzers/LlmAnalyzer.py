import os
import re  # <--- Ajout important pour nettoyer les balises <think>
from typing import List
from ollama import Client
from app.core.config_loader import ConfigLoader


class LlmAnalyzer:
    def __init__(self):
        self.config = ConfigLoader()
        self.model_name = self.config.get("llm.model_fallback", "gpt-oss:20b")

        # On augmente drastiquement le timeout car les modèles "Thinker" sont lents
        # 157s observées -> On met 600s (10min) pour être large sur les grosses pages
        self.timeout_val = int(self.config.get("llm.timeout_sec", 600))

        self.prompt_standard = self.config.get("llm.judge_prompt", "")
        self.prompt_extract = self.config.get("llm.extract_prompt", "")

        try:
            self.client = Client(host='http://localhost:11434', timeout=self.timeout_val)
        except Exception as e:
            print(f"   [LLM Warning] Client init failed: {e}")

    def get_final_redaction_list(self, page_text: str, initial_candidates: List[str], debug: bool = False) -> List[str]:
        if not page_text.strip():
            return []

        unique_candidates = sorted(list(set(initial_candidates)))
        count_candidates = len(unique_candidates)

        # Stratégie de bascule (densité)
        limit_high_density = 40
        if count_candidates > limit_high_density:
            if debug: print(f"   [LLM] Mode EXTRACTION (Densité: {count_candidates})")
            prompt = self.prompt_extract.format(page_text=page_text)
        else:
            if debug: print(f"   [LLM] Mode VALIDATION (Densité: {count_candidates})")
            candidates_str = "\n".join([f"- {c}" for c in unique_candidates])
            prompt = self.prompt_standard.format(page_text=page_text, candidates_str=candidates_str)

        if debug:
            print(f"   [LLM] Envoi requête (Timeout={self.timeout_val}s)...")

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'temperature': 0.6,  # Faible, mais pas 0.0 absolu pour éviter les boucles de raisonnement
                    'num_ctx': 16384,  # CRUCIAL: Mémoire large pour Page + Réflexion + Réponse
                    'num_predict': -1,  # CRUCIAL: Pas de limite de génération (-1 = infini)
                    # On retire les 'stop' tokens qui pourraient couper la réflexion
                    'stop': []
                }
            )

            raw_content = response['message']['content']

            # --- NETTOYAGE DES "PENSÉES" (<think>...</think>) ---
            # Les modèles type DeepSeek-R1 ou Chain-of-Thought mettent leur raisonnement dans ces balises.
            # Il faut les retirer pour ne garder que la réponse finale.
            clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

            if debug:
                print("\n" + "=" * 20 + " RÉPONSE LLM BRUTE (Sans <think>) " + "=" * 20)
                print(clean_content)
                print("=" * 60 + "\n")

            # --- Parsing de la liste ---
            final_terms = []
            for line in clean_content.split('\n'):
                # Nettoyage des puces markdown et espaces
                clean_line = line.strip().lstrip("-").lstrip("*").strip()

                # Filtrage des lignes parasites
                if len(clean_line) > 1:
                    # On évite de capturer des phrases d'intro du type "Voici la liste :"
                    if "voici" in clean_line.lower() and ":" in clean_line:
                        continue
                    if "liste" in clean_line.lower() and "masquer" in clean_line.lower():
                        continue

                    final_terms.append(clean_line)

            print(f"   [LLM] -> {len(final_terms)} termes identifiés.")
            return final_terms

        except Exception as e:
            print(f"   [LLM Error] {e}")
            if "Read timed out" in str(e):
                print("   [Conseil] Augmentez 'timeout_sec' dans config.yaml ou utilisez un modèle plus rapide.")
            return initial_candidates
import json
import os
import re
import time
from typing import List, Dict, Any
from dataclasses import asdict
from ollama import Client, ResponseError

from app.core.config_loader import ConfigLoader
from app.domain.models import AnonymizationCandidate


class LlmAnalyzer:
    """
    VERSION 2 (Architecture Juge) :
    Ce module ne cherche plus les entités lui-même.
    Il reçoit une liste de candidats (Regex/Presidio) et décide quoi garder/corriger.
    """

    def __init__(self):
        self.config = ConfigLoader()

        # Configuration Modèle
        self.model_name = os.getenv("ANONYMIZATION_MODEL", self.config.get("llm.model_fallback"))
        env_timeout = os.getenv("LLM_TIMEOUT_SEC")
        self.timeout_val = int(env_timeout) if env_timeout else self.config.get("llm.timeout_sec", 300)

        # Configuration Prompt Juge
        self.judge_prompt_template = self.config.get("llm.judge_prompt", "")

        print(f"   [LLM Juge] Modèle: {self.model_name} | Timeout: {self.timeout_val}s")

        try:
            self.client = Client(host='http://localhost:11434', timeout=self.timeout_val)
        except Exception as e:
            print(f"   [LLM] Erreur init client : {e}")

    def judge_candidates(self, page_text: str, candidates: List[AnonymizationCandidate]) -> List[Dict[str, Any]]:
        if not page_text or not candidates:
            return []

        # 1. Préparation
        candidates_json = [asdict(c) for c in candidates]
        candidates_str = json.dumps(candidates_json, indent=2, ensure_ascii=False)

        try:
            full_prompt = self.judge_prompt_template.format(
                candidate_list_json=candidates_str,
                page_text=page_text
            )
        except KeyError:
            return []

        print(f"   [LLM] 📤 Envoi de {len(candidates)} candidats (Mode 'Redact Only')...")

        # 2. Appel API avec paramètres optimisés
        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': full_prompt}],
                options={
                    'temperature': 0.0,
                    'num_predict': 2048,  # On laisse de la marge
                    'stop': ["Candidate:", "Texte:", "User:"]  # Stop words pour éviter les boucles
                }
            )
            content = response['message']['content']

            # 3. Parsing "Doux" (Soft Parsing)
            # On n'essaie plus de parser tout le bloc d'un coup, on cherche les items valides
            validated_items = self._soft_json_parse(content)

            final_entities = []

            # 4. Traitement
            for item in validated_items:
                text_to_hide = item.get("text")
                if not text_to_hide: continue

                # On cherche dans le texte
                found = False
                for match in re.finditer(re.escape(text_to_hide), page_text, re.IGNORECASE):
                    found = True
                    final_entities.append({
                        "start": match.start(),
                        "end": match.end(),
                        "type": item.get("type", "LLM_VALIDATED"),
                        "source": "LLM_JUDGE",
                        "text_slice": match.group()
                    })

                if not found:
                    # Petit log discret
                    pass

            print(f"   [LLM] ✅ {len(final_entities)} éléments confirmés pour masquage.")
            return final_entities

        except Exception as e:
            print(f"   [LLM Error] {e}")
            return []

    def _soft_json_parse(self, text: str) -> List[Dict]:
        """
        Extrait des objets JSON même si le format global est cassé.
        Cherche tous les motifs {...} et tente de les lire.
        """
        results = []

        # 1. Tentative propre (Global)
        try:
            # Nettoyage Markdown
            clean = text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            if "redactions" in data:
                return data["redactions"]
        except:
            pass  # On passe au mode "Soft"

        # 2. Tentative Regex (Item par item)
        # On cherche tout ce qui ressemble à un objet JSON simple
        # Regex : accolade ouvrante, tout sauf accolade fermante, accolade fermante
        import re
        # Cette regex capture les objets JSON simples (pas imbriqués)
        pattern = r"\{[^{}]+\}"

        matches = re.finditer(pattern, text)
        for match in matches:
            candidate_str = match.group()
            try:
                obj = json.loads(candidate_str)
                # Vérifie si c'est un item de redaction valide
                if "text" in obj:
                    results.append(obj)
            except:
                continue

        return results
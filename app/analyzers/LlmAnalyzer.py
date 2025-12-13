import json
import os
import time
from typing import List
from ollama import Client, ResponseError
from app.core.config_loader import ConfigLoader  # <--- Import


class LlmAnalyzer:
    def __init__(self):
        self.config = ConfigLoader()

        self.model_name = os.getenv("ANONYMIZATION_MODEL", self.config.get("llm.model_fallback"))
        # Priorité : ENV > Config > Défaut
        env_timeout = os.getenv("LLM_TIMEOUT_SEC")
        self.timeout_val = int(env_timeout) if env_timeout else self.config.get("llm.timeout_sec", 300)

        self.max_chars = self.config.get("llm.max_chars_context", 4000)

        # On charge le prompt système une seule fois
        self.system_prompt_template = self.config.get("llm.system_prompt", "")

        print(f"   [LLM] Modèle: {self.model_name} | Timeout: {self.timeout_val}s")

        try:
            self.client = Client(host='http://localhost:11434', timeout=self.timeout_val)
        except Exception as e:
            print(f"   [LLM] Erreur init client : {e}")

    def analyze_text(self, text: str) -> List[str]:
        if not text or len(text.strip()) < 5:
            return []

        # Troncature dynamique
        if len(text) > self.max_chars:
            print(f"   [LLM] ⚠️ Troncature ({len(text)} > {self.max_chars})")
            text_preview = text[:self.max_chars]
        else:
            text_preview = text

        # Construction du prompt final
        # On injecte le texte à analyser à la suite du prompt système défini dans le YAML
        full_prompt = f"""
        {self.system_prompt_template}

        Texte à analyser :
        "{text_preview}"
        """

        try:
            # Appel API
            response = self.client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': full_prompt}],
                options={'temperature': 0.0, 'num_ctx': 4096, 'num_predict': 500}
            )

            content = response['message']['content']

            # Parsing JSON (inchangé)
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = content[json_start:json_end]
                try:
                    data = json.loads(json_str)
                    return data.get("sensitive_phrases", [])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        except Exception:
            return []  # On reste silencieux sur les erreurs unitaires ici pour alléger le log
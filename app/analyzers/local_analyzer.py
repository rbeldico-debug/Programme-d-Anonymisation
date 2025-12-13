from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider
from typing import List, Dict
from app.core.config_loader import ConfigLoader  # <--- Import


class LocalAnalyzer:
    def __init__(self):
        self.config = ConfigLoader()
        self.language = self.config.get("presidio.language", "fr")

        # 1. Configuration Spacy
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": self.language, "model_name": "fr_core_news_lg"}],
        }

        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()

        self.analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=[self.language]
        )

        # 2. Chargement Dynamique des Règles Regex
        self._load_custom_rules()

    def _load_custom_rules(self):
        """Lit les règles custom depuis config.yaml et les injecte."""
        rules = self.config.get("presidio.custom_rules", [])

        for rule in rules:
            try:
                pattern = Pattern(name=rule['name'], regex=rule['regex'], score=rule['score'])
                recognizer = PatternRecognizer(
                    supported_entity=rule['entity_type'],
                    name=f"Custom_{rule['name']}",
                    patterns=[pattern],
                    supported_language=self.language
                )
                self.analyzer.registry.add_recognizer(recognizer)
                # print(f"   [Presidio] Règle chargée : {rule['name']}")
            except Exception as e:
                print(f"   [Presidio] Erreur chargement règle {rule.get('name')}: {e}")

    def analyze_text(self, text: str) -> List[Dict]:
        if not text: return []

        # Récupération des entités cibles depuis la config
        target_entities = self.config.get("presidio.active_entities", ["PERSON", "LOCATION"])
        threshold = self.config.get("presidio.score_threshold", 0.4)

        results = self.analyzer.analyze(
            text=text,
            language=self.language,
            entities=target_entities,
            score_threshold=threshold
        )

        structured_results = []
        for res in results:
            structured_results.append({
                "type": res.entity_type,
                "start": res.start,
                "end": res.end,
                "score": res.score,
                "text_slice": text[res.start:res.end]
            })

        return structured_results
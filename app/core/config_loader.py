import yaml
import os
from typing import Dict, Any


class ConfigLoader:
    _instance = None
    _config = None

    def __new__(cls):
        """Singleton pattern pour ne charger la config qu'une fois."""
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        config_path = "config.yaml"
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de configuration (ex: 'presidio.language')."""
        keys = key.split('.')
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
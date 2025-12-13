import os
import re
from typing import List, Dict, Set


class FilterEngine:
    """
    Gère les listes blanches (Allowlist) et noires (Blocklist) définies par l'utilisateur.
    """

    def __init__(self, dict_dir: str = "data/dictionaries"):
        self.whitelist: Set[str] = set()
        self.blacklist: Set[str] = set()

        self._load_list(os.path.join(dict_dir, "whitelist.txt"), self.whitelist)
        self._load_list(os.path.join(dict_dir, "blacklist.txt"), self.blacklist)

    def _load_list(self, filepath: str, target_set: Set[str]):
        """Charge un fichier texte (un mot/phrase par ligne) dans un set."""
        if not os.path.exists(filepath):
            # On crée le fichier vide s'il n'existe pas pour faciliter la vie de l'utilisateur
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                pass
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                clean_line = line.strip().lower()
                if clean_line and not clean_line.startswith("#"):
                    target_set.add(clean_line)

        print(f"   [Filter] Chargé {os.path.basename(filepath)} : {len(target_set)} entrées.")

    def apply_filters(self, text: str, detected_entities: List[Dict]) -> List[Dict]:
        """
        1. Supprime les entités qui sont dans la Whitelist.
        2. Ajoute les entités qui sont dans la Blacklist (recherche dans le texte).
        """

        # --- 1. WHITELIST (Suppression) ---
        # On garde seulement les entités dont le texte n'est PAS dans la whitelist
        filtered_entities = []
        for entity in detected_entities:
            entity_text = text[entity['start']:entity['end']].lower().strip()

            # Vérification exacte
            if entity_text in self.whitelist:
                # Logique debug : on pourrait logger ce qu'on a sauvé
                continue

            # Vérification "contient" (Optionnel, parfois risqué)
            # Si le mot whitelisté est "clinique", on veut peut-être sauver "clinique pasteur" ?
            # Pour l'instant, restons sur du match exact ou sub-string strict.

            filtered_entities.append(entity)

        # --- 2. BLACKLIST (Ajout forcé) ---
        # On scanne le texte pour trouver les mots interdits
        for bad_word in self.blacklist:
            # On utilise regex escape pour éviter les crashs si le mot contient des parenthèses
            # \b permet de chercher le mot entier (évite de masquer "ass" dans "passer")
            pattern = re.compile(re.escape(bad_word), re.IGNORECASE)

            for match in pattern.finditer(text):
                # On vérifie si ce n'est pas déjà détecté pour éviter les doublons
                # (Simplification : on l'ajoute, le TextMapper gérera les chevauchements)
                filtered_entities.append({
                    "type": "MANUAL_BLACKLIST",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 1.0,
                    "source": "USER_BLACKLIST",
                    "text_slice": match.group()
                })

        return filtered_entities
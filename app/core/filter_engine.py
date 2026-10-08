import os
import re
import unicodedata
from typing import List, Dict, Set

from app.core import registre as registre_mod


# --- Forme normalisée d'un terme, pour COMPARER (jamais pour chercher dans le texte) ---------------
# Casse repliée, Unicode NFC, apostrophes et espaces unifiées, ponctuation de bord retirée.
# Les ACCENTS sont GARDÉS, exprès : la liste blanche DÉMASQUE, l'élargir est une fuite possible
# (« lefevre » en liste blanche ne doit pas libérer « Lefèvre »).
_APOSTROPHES = "'’ʼ‘`´"
_BORD = " \t\r\n.,;:!?…()[]{}\"«»“”"


def normaliser_terme(terme: str) -> str:
    t = unicodedata.normalize("NFC", terme or "")
    for a in _APOSTROPHES[1:]:
        t = t.replace(a, "'")
    t = t.replace(" ", " ").replace(" ", " ").replace("­", "")
    t = re.sub(r"\s+", " ", t).strip(_BORD + "'")
    return t.casefold()


def motif_mot_entier(terme: str) -> str:
    """Motif d'un terme cherché EN MOT ENTIER (à compiler avec re.IGNORECASE).

    - bornes Unicode : pas de lettre, chiffre ou accent combinant collé au terme (« fort » ne mord
      pas dans « effort » ni dans « forté ») ; une borne n'est posée que du côté où le terme finit
      par un caractère de mot : « Dr Dupont. » se trouve aussi devant une espace ou en fin de texte
      (avec \\b des deux côtés, il ne se trouvait JAMAIS) ;
    - apostrophes françaises interchangeables (' ’ ʼ) ; après une élision, le mot se trouve
      (« Orléans » dans « d'Orléans ») ;
    - un blanc du terme accepte n'importe quelle suite de blancs (fin de ligne comprise)."""
    t = unicodedata.normalize("NFC", terme.strip())
    if not t:
        raise ValueError("terme vide")
    corps = []
    for c in t:
        if c in _APOSTROPHES:
            corps.append("['’ʼ‘]")
        elif c.isspace():
            if not corps or corps[-1] != r"\s+":
                corps.append(r"\s+")
        else:
            corps.append(re.escape(c))
    debut = r"(?<![\ẁ-ͯ])" if re.match(r"\w", t) else ""
    fin = r"(?![\ẁ-ͯ])" if re.search(r"\w$", t) else ""
    return debut + "".join(corps) + fin


class FilterEngine:
    """
    Gère les listes blanches (Allowlist) et noires (Blocklist) définies par l'utilisateur,
    et le REGISTRE des entrées déjà masquées (registre.tsv, voir app/core/registre.py).

    Priorités :
      - liste noire (écrite à la main) : toujours masquée, même si la liste blanche la contient ;
      - liste blanche : l'emporte sur TOUT ce qui est automatique — le registre, les détections ;
      - registre : masqué partout, sauf ce que la liste blanche libère.
    """

    def __init__(self, dict_dir: str = None):
        # Dossier configurable par ANONYMIZER_DICT_DIR : la liste noire est une donnée SENSIBLE,
        # destinée à vivre hors de ce dépôt (compte Linux séparé). Sans la variable, comportement
        # inchangé : "data/dictionaries".
        if dict_dir is None:
            dict_dir = os.environ.get("ANONYMIZER_DICT_DIR", "data/dictionaries")
        self.dict_dir = dict_dir
        self.whitelist: Set[str] = set()
        self.blacklist: Set[str] = set()

        self._load_list(os.path.join(dict_dir, "whitelist.txt"), self.whitelist)
        self._load_list(os.path.join(dict_dir, "blacklist.txt"), self.blacklist)
        # La liste blanche se compare sous forme normalisée (casse, apostrophes, ponctuation de bord).
        self.whitelist = {normaliser_terme(w) for w in self.whitelist} - {""}

        # Le registre : les entrées (mot entier, sans égard à la casse) et leurs variantes (mot
        # entier, initiale MAJUSCULE exigée). La liste blanche l'emporte : ce qu'elle contient
        # n'est pas chargé.
        self.registre_entrees: Set[str] = set()
        self.registre_variantes: Set[str] = set()
        self.registre_ecartes = 0
        chemin = os.path.join(dict_dir, registre_mod.NOM_FICHIER)
        if os.path.exists(chemin):
            reg = registre_mod.lire(chemin)
            for e in reg.entrees:
                if self.est_blanc(e.entree):
                    self.registre_ecartes += 1
                else:
                    self.registre_entrees.add(e.entree)
                for v in e.variantes:
                    if self.est_blanc(v):
                        self.registre_ecartes += 1
                    else:
                        self.registre_variantes.add(v)
            # Une variante qui est aussi une entrée garde le traitement de l'entrée.
            cles_entrees = {normaliser_terme(e) for e in self.registre_entrees}
            self.registre_variantes = {v for v in self.registre_variantes
                                       if normaliser_terme(v) not in cles_entrees}
            print(f"   [Filter] Chargé {registre_mod.NOM_FICHIER} : {len(self.registre_entrees)} entrées, "
                  f"{len(self.registre_variantes)} variantes ({self.registre_ecartes} libérées par la liste blanche).")

    def est_blanc(self, terme: str) -> bool:
        """Le terme est-il dans la liste blanche (forme normalisée) ?"""
        return normaliser_terme(terme) in self.whitelist

    # Ce que la passe 2 cherche en plus des détections, et comment.
    def a_masquer(self) -> Set[str]:
        return set(self.blacklist) | self.registre_entrees | self.registre_variantes

    def formes_bornees(self) -> Set[str]:
        """Formes (minuscules) cherchées en mot entier, sans égard à la casse."""
        return set(self.blacklist) | {e.lower() for e in self.registre_entrees}

    def formes_majuscule(self) -> Set[str]:
        """Formes (minuscules) cherchées en mot entier, initiale majuscule exigée dans le texte."""
        return {v.lower() for v in self.registre_variantes}

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
        1. Supprime les entités qui sont dans la Whitelist (forme normalisée).
        2. Ajoute les entités qui sont dans la Blacklist (recherche dans le texte, MOT ENTIER).
        (Le pipeline n'appelle pas cette méthode : il passe par noms_composes.motifs, qui borne de
        la même façon, par motif_mot_entier.)
        """
        filtered_entities = [e for e in detected_entities
                             if not self.est_blanc(text[e['start']:e['end']])]

        for bad_word in self.blacklist:
            pattern = re.compile(motif_mot_entier(bad_word), re.IGNORECASE)
            for match in pattern.finditer(text):
                filtered_entities.append({
                    "type": "MANUAL_BLACKLIST",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 1.0,
                    "source": "USER_BLACKLIST",
                    "text_slice": match.group()
                })

        return filtered_entities

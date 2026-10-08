"""Les MOTS COURANTS du français, pour la garde du registre (outils/registre.py).

Source, déjà installée : le modèle spaCy fr_core_news_lg (licence LGPL-LR, sources listées dans son
LICENSES_SOURCES), que Presidio charge de toute façon. Rien n'en est recopié dans ce dépôt : la liste
est LUE dans le venv à chaque récolte (moins d'une seconde).
  1. les mots-outils de spaCy (spacy.lang.fr.stop_words, 507 mots) ;
  2. le LEXIQUE du lemmatiseur du modèle (lemmatizer/lookups, table lemma_index : 94 954 lemmes
     de noms communs, verbes, adjectifs et adverbes — « leroy », « paris » n'y sont pas) ;
  3. le RANG de chaque forme dans la table de vecteurs du modèle (vocab/key2row : 500 000 formes,
     sensibles à la casse, rangées par fréquence — constaté le 08/10/2026 : « de » 1, « le » 7, « petit »
     215, « sommeil » 3 605 ; ce n'est pas documenté par spaCy, c'est mesuré).

Un mot est COURANT s'il est un mot-outil, ou si sa forme en minuscules est AU LEXIQUE et parmi les
SEUIL formes les plus fréquentes, avec une condition de plus pour un NOM commun : être plus fréquent en
minuscules qu'avec une majuscule initiale. Cette condition sauve les prénoms et noms qui sont aussi des
noms communs :
« Pierre » (787) passe devant « pierre » (1 371), « Martin » (2 196) devant « martin » (29 666) — ils
restent inscriptibles. « Claire », « Rose », « Fort », « Petit », « Fontaine » sont courants : seuls, ils
ne sont jamais inscrits (un « Jean Petit » entier l'est, sa variante « Petit » non).
"""
import importlib.util
import os
import re

SEUIL = 20000


class MotsCourants:
    def __init__(self, seuil: int = SEUIL):
        import srsly
        from spacy.lang.fr.stop_words import STOP_WORDS
        from spacy.strings import hash_string
        self.seuil = seuil
        self._hash = hash_string
        self.stop = {w.lower() for w in STOP_WORDS}
        spec = importlib.util.find_spec("fr_core_news_lg")
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("fr_core_news_lg introuvable : pas de liste de mots courants, récolte refusée")
        racine = list(spec.submodule_search_locations)[0]
        chemins = [os.path.join(r, "key2row") for r, _, f in os.walk(racine) if "key2row" in f]
        if not chemins:
            raise RuntimeError("table key2row introuvable dans fr_core_news_lg : récolte refusée")
        self._rang = srsly.read_msgpack(chemins[0])
        from spacy.lookups import Lookups
        tables = [r for r, _, f in os.walk(racine) if "lookups.bin" in f and r.endswith(os.path.join("lemmatizer", "lookups"))]
        if not tables:
            raise RuntimeError("lexique du lemmatiseur introuvable dans fr_core_news_lg : récolte refusée")
        self.lexique = set()
        self.noms_communs = set()
        cle_nom = hash_string("noun")
        for pos, lemmes in Lookups().from_disk(tables[0]).get_table("lemma_index").items():
            self.lexique.update(l.lower() for l in lemmes)
            if pos in (cle_nom, "noun"):
                self.noms_communs.update(l.lower() for l in lemmes)
        # Un adverbe, un verbe, un adjectif qui n'est PAS aussi un nom commun : courant même s'il
        # est plus fréquent en tête de phrase (« Heureusement » 5 058 contre « heureusement » 5 388).
        self.autres = self.lexique - self.noms_communs

    def rang(self, forme: str):
        return self._rang.get(self._hash(forme))

    def est_courant(self, mot: str) -> bool:
        m = re.sub(r"^[dlDL]['’]", "", mot.strip(" .,;:!?'’()«»\""))
        if not m:
            return False
        bas = m.lower()
        if bas in self.stop:
            return True
        if bas not in self.lexique:
            return False
        r_bas = self.rang(bas)
        if r_bas is None or r_bas >= self.seuil:
            return False
        if bas in self.autres:
            return True
        r_cap = self.rang(bas[:1].upper() + bas[1:])
        return r_cap is None or r_bas <= r_cap

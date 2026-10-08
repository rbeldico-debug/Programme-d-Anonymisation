"""Variantes des termes rendus par le LLM, pour que la forme ENTIÈRE d'un nom ne soit pas la seule
masquée.

Le défaut (07/10/2026) : le masquage cherche la chaîne EXACTE rendue par le LLM. Si le LLM ne rend
que « Clémence Ardouin-Vasseur », la 2e occurrence « Dr Ardouin-Vasseur. » reste en clair (1 tirage
sur 3 dans la mesure du 05/10). Ce module dérive, d'un terme rendu, des formes plus courtes à
chercher AUSSI — la forme entière reste toujours cherchée, telle quelle.

Niveaux, cumulatifs (config.yaml, masquage.noms_composes) :
  - "aucun"   : comportement d'avant, chaîne exacte seulement ;
  - "titres"  : + la forme sans civilité ni ponctuation finale (« Dr Ardouin-Vasseur. » -> « Ardouin-Vasseur ») ;
  - "parties" : + chaque mot d'un terme QUI A LA FORME D'UN NOM DE PERSONNE (« Clémence Ardouin-Vasseur »
                -> « Clémence », « Ardouin-Vasseur ») ; un nom à trait d'union reste ENTIER ;
  - "civilites" : + les morceaux d'un nom à trait d'union, mais SEULEMENT juste après une civilité
                (« Dr Ardouin », « Mme Vasseur ») ; « Grand Est » ne bouge pas pour « Grand-Vallat » ;
  - "traits"  : + les morceaux d'un nom à trait d'union PARTOUT (« Ardouin-Vasseur » -> « Ardouin », « Vasseur »).

Garde-fous d'une forme DÉRIVÉE (jamais de la forme rendue par le LLM, qui garde son ancien traitement) :
  - mot entier seulement (\\b des deux côtés) : « Marc » ne mord pas dans « marché » ;
  - initiale MAJUSCULE exigée dans le texte : « Rose » (prénom) ne masque pas « érythème rose » ;
  - ni particule (de, Le, Van…), ni civilité, ni mot de moins de 3 lettres ;
  - une partie n'est tirée que d'un terme sans chiffre, sans @, sans mot d'institution ou de voirie,
    dont tous les mots (hors particules) ont une initiale majuscule.
"""
import re
from typing import Iterable, List, Set, Tuple

NIVEAUX = ("aucun", "titres", "parties", "civilites", "traits")

_CIVILITES = {"dr", "docteur", "pr", "professeur", "m", "mr", "mme", "mmes", "mlle", "melle", "me",
              "monsieur", "madame", "mademoiselle", "maître", "maitre", "messieurs"}
_PARTICULES = {"de", "du", "des", "d'", "la", "le", "les", "l'", "van", "von", "der", "den", "ter", "di", "da",
               "del", "della", "dos", "das", "do", "el", "al", "ben", "bin", "ibn", "y", "e", "et",
               "saint", "sainte", "st", "ste"}
# Un terme qui contient l'un de ces mots est un lieu ou une institution, pas un nom de personne :
# « Hôpital Nord » ne doit jamais donner « Nord ».
_MOTS_LIEU = {"hôpital", "hopital", "clinique", "chu", "chr", "ch", "chs", "centre", "cmp", "cmpp", "ehpad",
              "service", "unité", "cabinet", "maison", "pôle", "institut", "fondation", "foyer", "résidence",
              "tribunal", "cour", "mairie", "école", "collège", "lycée", "université", "rue", "avenue", "av",
              "allée", "impasse", "place", "chemin", "boulevard", "bd", "route", "quai", "cours", "square",
              "lieu-dit", "hameau", "zone", "région", "département", "ville", "commune", "pavillon",
              "bâtiment", "secteur", "groupe", "association", "cedex", "bp"}

_MAJ = "A-ZÀ-ÖØ-ÞŒ"
_TITRE_EN_TETE = re.compile(r"^(?:(?:%s)\.?\s+)+" % "|".join(sorted((re.escape(c) for c in _CIVILITES),
                                                                     key=len, reverse=True)),
                            re.IGNORECASE)
_PONCT_FIN = re.compile(r"[\s.,;:!?…)\]\"'»”]+$")
_PONCT_DEBUT = re.compile(r"^[\s(\[\"'«“]+")


def forme_nue(terme: str) -> str:
    """Le terme sans civilité en tête ni ponctuation autour (« Dr Ardouin-Vasseur. » -> « Ardouin-Vasseur »)."""
    t = _PONCT_DEBUT.sub("", terme.strip())
    t = _PONCT_FIN.sub("", t)
    t = _TITRE_EN_TETE.sub("", t)
    return t.strip()


def _lettres(mot: str) -> int:
    return sum(1 for c in mot if c.isalpha())


def _majuscule(mot: str) -> bool:
    return bool(mot) and mot[0].isalpha() and mot[0].isupper()


def a_forme_de_nom(terme: str) -> bool:
    """Un terme qui ressemble à un nom de personne : 1 à 5 mots, aucun chiffre ni @, aucun mot de lieu
    ou d'institution, et chaque mot (hors particules) commence par une majuscule. Les morceaux d'un
    mot à trait d'union sont regardés un à un : « Morvillars-le-Haut » (un « le » en minuscule) est
    un toponyme, pas un nom composé."""
    t = forme_nue(terme)
    if not t or any(c.isdigit() for c in t) or "@" in t or "/" in t:
        return False
    mots = t.split()
    if not 1 <= len(mots) <= 5:
        return False
    for mot in mots:
        bas = mot.lower().strip(".,;:")
        if bas in _MOTS_LIEU:
            return False
        if bas in _PARTICULES or bas in _CIVILITES:
            continue
        for morceau in mot.split("-"):
            if not morceau:
                continue
            if morceau.lower() in _MOTS_LIEU:
                return False
            morceau = re.sub(r"^[dl]['’]", "", morceau, flags=re.IGNORECASE)
            if not _majuscule(morceau):
                return False
    return True


def _partie_valable(mot: str) -> bool:
    bas = mot.lower()
    return (_lettres(mot) >= 3 and bas not in _PARTICULES and bas not in _CIVILITES
            and bas not in _MOTS_LIEU and _majuscule(mot))


def _sous_composes(mot: str) -> Set[str]:
    """Les suites CONTIGUËS de morceaux d'un nom à trait d'union, sauf le nom entier :
    « Saint-Martin-Lacoste » -> « Saint-Martin », « Martin-Lacoste », « Martin », « Lacoste »
    (« Saint » seul est une particule : jamais)."""
    pieces = [p for p in mot.strip(".,;:").split("-")]
    sortie = set()
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces) + 1):
            if j - i == len(pieces):
                continue
            forme = "-".join(pieces[i:j])
            if j - i == 1:
                if _partie_valable(forme):
                    sortie.add(forme)
            elif all(pieces[i:j]) and _lettres(forme) >= 3 and _majuscule(forme):
                sortie.add(forme)
    return sortie


def deriver(termes: Iterable[str], niveau: str = "aucun") -> Set[str]:
    """Les formes DÉRIVÉES à chercher en plus des termes rendus (jamais un terme déjà rendu tel quel).
    Elles se cherchent avec les garde-fous de motif_derive()."""
    if niveau not in NIVEAUX:
        raise ValueError(f"masquage.noms_composes : niveau inconnu {niveau!r} (attendu : {', '.join(NIVEAUX)})")
    if niveau == "aucun":
        return set()
    rendus = {t.strip().lower() for t in termes}
    derives = set()
    for terme in termes:
        nu = forme_nue(terme)
        if nu and _lettres(nu) >= 3 and nu.lower() not in _PARTICULES:
            derives.add(nu)
        if niveau in ("parties", "civilites", "traits") and a_forme_de_nom(terme):
            for mot in nu.split():
                mot = mot.strip(".,;:")
                if _partie_valable(mot):
                    derives.add(mot)
                if niveau == "traits" and "-" in mot:
                    derives |= _sous_composes(mot)
    return {d for d in derives if d.lower() not in rendus}


def morceaux(termes: Iterable[str]) -> Set[str]:
    """Les morceaux des noms à trait d'union (« Clémence Ardouin-Vasseur » -> « Ardouin », « Vasseur »),
    tirés des seuls termes qui ont la forme d'un nom de personne."""
    sortie = set()
    for terme in termes:
        if not a_forme_de_nom(terme):
            continue
        for mot in forme_nue(terme).split():
            if "-" in mot:
                sortie |= _sous_composes(mot)
    return sortie


# Civilité juste avant : une lookbehind de largeur fixe par forme (« Dr », « Dr. », « Mme »…).
_APRES_CIVILITE = "(?:" + "|".join(
    r"(?<=\b%s%s)" % (re.escape(c), sep)
    for c in sorted(_CIVILITES, key=len, reverse=True) for sep in (" ", ". ")) + ")"


def motif_apres_civilite(forme: str) -> str:
    """Le morceau seul, mais seulement juste après une civilité (qui, elle, n'est pas masquée)."""
    return _APRES_CIVILITE + motif_derive(forme)


def motif_derive(forme: str) -> str:
    """Mot entier, initiale MAJUSCULE dans le texte (le reste insensible à la casse : ARDOUIN, Ardouin)."""
    debut = r"\b(?-i:(?=[%s]))" % _MAJ if forme[:1].isalpha() else (r"\b" if re.match(r"\w", forme) else "")
    fin = r"\b" if re.search(r"\w$", forme) else ""
    return debut + re.escape(forme) + fin


def motifs(termes: Iterable[str], liste_noire: Set[str], niveau: str = "aucun",
           majuscule: Set[str] = frozenset()) -> List[Tuple[str, str]]:
    """(terme, motif regex) pour chaque terme rendu et chaque forme dérivée (motif_derive). À compiler
    avec re.IGNORECASE. Le plus long d'abord.
    - terme de `liste_noire` (liste noire, entrées du registre) : MOT ENTIER (filter_engine.motif_mot_entier :
      bornes Unicode posées seulement sur un bord alphanumérique, apostrophes interchangeables) ;
    - terme de `majuscule` (variantes du registre) : mot entier, initiale majuscule (motif_derive) ;
    - autre terme : la chaîne telle quelle, sans borne (traitement d'avant)."""
    from app.core.filter_engine import motif_mot_entier
    termes = [t for t in termes if t and t.strip()]
    paires = []
    for t in termes:
        cle = t.strip().lower()
        if cle in liste_noire:
            m = motif_mot_entier(t)
        elif cle in majuscule:
            m = motif_derive(t.strip())
        else:
            m = re.escape(t)
        paires.append((t, m))
    derives = deriver(termes, niveau)
    for d in derives:
        paires.append((d, motif_derive(d)))
    if niveau == "civilites":
        rendus = {t.strip().lower() for t in termes} | {d.lower() for d in derives}
        for m in morceaux(termes):
            if m.lower() not in rendus:
                paires.append((m, motif_apres_civilite(m)))
    paires.sort(key=lambda p: len(p[0]), reverse=True)
    return paires


def motif_unique(termes: Iterable[str], liste_noire: Set[str], niveau: str = "aucun",
                 majuscule: Set[str] = frozenset()):
    """Une seule regex, alternance du plus long au plus court (le mode texte remplace en UNE passe)."""
    paires = motifs(termes, liste_noire, niveau, majuscule)
    if not paires:
        return None
    return re.compile("|".join(m for _, m in paires), re.IGNORECASE)

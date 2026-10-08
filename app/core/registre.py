"""Le REGISTRE des entrées masquées : « un mot qui a été masqué doit l'être pour toujours » (hedrox, 08/10/2026).

Il vit À CÔTÉ des listes blanche et noire, dans ANONYMIZER_DICT_DIR (au bureau : le coffre). C'est une
donnée SENSIBLE (des noms en clair) : rien ici ne l'imprime, seuls des COMPTES sortent.

Format (registre.tsv), lisible et éditable dans un éditeur de texte :

    # commentaire
    2026-10-08<TAB>PERSON<TAB>Clémence Ardouin-Vasseur<TAB>Clémence | Ardouin-Vasseur | Ardouin | Vasseur

    colonne 1 : date de la première récolte (AAAA-MM-JJ)
    colonne 2 : type d'entité lu dans l'audit (PERSON, LOCATION, LLM, INCONNU…) — informatif
    colonne 3 : l'ENTRÉE, telle qu'elle a été masquée — cherchée en mot entier, sans égard à la casse
    colonne 4 : ses VARIANTES séparées par « | » — cherchées en mot entier, initiale MAJUSCULE exigée
                (« Rose » le prénom, pas « érythème rose »)

Rien n'est jamais retiré automatiquement. Pour qu'un mot ne soit plus masqué, on l'écrit dans
whitelist.txt : elle l'emporte sur le registre (FilterEngine). Une ligne illisible est gardée telle
quelle à la réécriture et comptée.
"""
import collections
import csv
import datetime
import fcntl
import glob
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set

NOM_FICHIER = "registre.tsv"
SEP_VARIANTES = " | "

EN_TETE = """\
# REGISTRE DES ENTRÉES MASQUÉES — anonymiseur (outils/registre.py recolter)
# Une ligne = une entrée : date <TAB> type <TAB> entrée <TAB> variantes séparées par « | ».
# Tout ce qui est ici est masqué dans TOUS les documents des passes suivantes :
#   l'entrée en mot entier, sans égard à la casse ; une variante en mot entier, initiale majuscule exigée.
# Rien n'est retiré automatiquement. Pour qu'un mot ne soit plus masqué : l'écrire dans whitelist.txt,
# qui l'emporte. Effacer une ligne ici est possible, mais une récolte suivante peut la remettre.
# Une ligne qui commence par # est ignorée.
"""

# Types que les règles fixes (regex) attrapent de toute façon à chaque passe : les inscrire ne sert à
# rien et gonflerait le registre. Une date en lettres, un numéro : la règle les retrouvera.
TYPES_REGLES = {"DATE", "DATE_TIME", "PHONE_NUMBER", "EMAIL_ADDRESS", "FR_SSN", "FR_RPPS"}
# Sources déjà permanentes : ne pas les recopier.
SOURCES_PERMANENTES = {"REGISTRE", "LISTE_NOIRE"}

LETTRES_MIN = 3
MOTS_MAX = 6
CARACTERES_MAX = 80


@dataclass
class Entree:
    date: str
    type: str
    entree: str
    variantes: List[str] = field(default_factory=list)

    def ligne(self) -> str:
        return "\t".join([self.date, self.type, self.entree, SEP_VARIANTES.join(self.variantes)]).rstrip("\t") + "\n"


@dataclass
class Registre:
    lignes: List[object]          # str (commentaire, ligne illisible, vide) ou Entree, dans l'ordre du fichier
    illisibles: int = 0

    @property
    def entrees(self) -> List[Entree]:
        return [l for l in self.lignes if isinstance(l, Entree)]


def _propre(s: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", s).strip()


def lire(chemin: str) -> Registre:
    reg = Registre(lignes=[])
    if not os.path.exists(chemin):
        return reg
    with open(chemin, encoding="utf-8") as f:
        for brute in f:
            l = brute.rstrip("\n")
            if not l.strip() or l.lstrip().startswith("#"):
                reg.lignes.append(brute if brute.endswith("\n") else brute + "\n")
                continue
            champs = l.split("\t")
            if len(champs) < 3 or not champs[2].strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", champs[0].strip()):
                reg.illisibles += 1
                reg.lignes.append(brute if brute.endswith("\n") else brute + "\n")
                continue
            variantes = [v.strip() for v in champs[3].split("|")] if len(champs) > 3 else []
            reg.lignes.append(Entree(champs[0].strip(), champs[1].strip(), champs[2].strip(),
                                     [v for v in variantes if v]))
    return reg


def ecrire(chemin: str, reg: Registre):
    """Écriture ATOMIQUE (fichier temporaire du même dossier, fsync, os.replace), droits 0600."""
    dossier = os.path.dirname(os.path.abspath(chemin))
    os.makedirs(dossier, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".registre-", suffix=".tmp", dir=dossier)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if not reg.lignes or not (isinstance(reg.lignes[0], str) and reg.lignes[0].startswith("# REGISTRE")):
                f.write(EN_TETE)
            for l in reg.lignes:
                f.write(l.ligne() if isinstance(l, Entree) else l)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, chemin)
        dfd = os.open(dossier, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Verrou:
    """Verrou exclusif à côté du registre : deux récoltes simultanées ne s'écrasent pas."""

    def __init__(self, chemin: str):
        self.chemin = chemin + ".verrou"

    def __enter__(self):
        self.fd = os.open(self.chemin, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


# --- Lecture des audits ---------------------------------------------------------------------------

def fichiers_audit(dossiers: Iterable[str]) -> List[str]:
    sortie = []
    for d in dossiers:
        if os.path.isfile(d) and d.endswith("_audit.csv"):
            sortie.append(d)
        else:
            sortie.extend(glob.glob(os.path.join(glob.escape(d), "**", "*_audit.csv"), recursive=True))
    return sorted(set(sortie))


def lire_audit(chemin: str) -> List[Dict[str, str]]:
    with open(chemin, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames or "text" not in r.fieldnames:
            raise ValueError("colonnes inattendues")
        return [dict(l) for l in r]


# --- La récolte -----------------------------------------------------------------------------------

_ELISION = re.compile(r"^[dl]['’ʼ](?=[A-ZÀ-ÖØ-ÞŒ])", re.IGNORECASE)


def variantes_de(terme: str) -> Set[str]:
    """Les variantes d'une entrée : celles de noms_composes au niveau « traits » (forme sans civilité,
    mots d'un nom de personne, morceaux d'un nom à trait d'union), plus la forme sans élision d'un nom
    à particule (« d’Estrébourg » -> « Estrébourg »). Chacune passe ensuite les gardes de recolter()."""
    from app.core import noms_composes
    sortie = set(noms_composes.deriver([terme], "traits"))
    if noms_composes.a_forme_de_nom(terme):
        for mot in noms_composes.forme_nue(terme).split():
            nu = _ELISION.sub("", mot.strip(".,;:"))
            if nu != mot.strip(".,;:") and nu:
                sortie.add(nu)
                if "-" in nu:
                    sortie |= noms_composes._sous_composes(nu)
    return sortie


def _lettres(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def _affichage(s: str) -> str:
    """La forme écrite au registre : blancs réduits, ponctuation de bord retirée."""
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" .,;:!?…()[]{}\"«»“”")


def _mots(s: str) -> List[str]:
    return re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", s)


@dataclass
class Bilan:
    audits: int = 0
    audits_illisibles: int = 0
    lignes_audit: int = 0
    termes_distincts: int = 0
    types_regles: int = 0
    deja_permanents: int = 0
    liste_blanche: int = 0
    liste_noire: int = 0
    deja_au_registre: int = 0
    trop_courts: int = 0
    trop_longs: int = 0
    suspects_mot_courant: int = 0
    suspects_minuscules: int = 0
    nouvelles_entrees: int = 0
    nouvelles_variantes: int = 0
    variantes_ecartees: int = 0
    registre_avant: int = 0
    registre_apres: int = 0
    lignes_illisibles: int = 0

    def lignes_comptes(self) -> List[str]:
        return [
            f"audits lus : {self.audits} ({self.audits_illisibles} illisibles) ; occurrences : {self.lignes_audit} ; "
            f"termes distincts : {self.termes_distincts}",
            f"écartés sans examen : {self.types_regles} de type règle fixe (dates, téléphones…), "
            f"{self.deja_permanents} venus du registre ou de la liste noire",
            f"déjà couverts : {self.deja_au_registre} au registre, {self.liste_noire} en liste noire ; "
            f"libérés par la liste blanche : {self.liste_blanche}",
            f"refusés par les gardes : {self.trop_courts} trop courts (< {LETTRES_MIN} lettres), "
            f"{self.trop_longs} trop longs (> {MOTS_MAX} mots ou {CARACTERES_MAX} caractères)",
            f"SUSPECTS refusés (non affichés) : {self.suspects_mot_courant} mots courants, "
            f"{self.suspects_minuscules} tout en minuscules",
            f"ajoutés : {self.nouvelles_entrees} entrées, {self.nouvelles_variantes} variantes "
            f"({self.variantes_ecartees} variantes refusées par les gardes)",
            f"registre : {self.registre_avant} -> {self.registre_apres} entrées"
            + (f" ; {self.lignes_illisibles} lignes illisibles gardées telles quelles" if self.lignes_illisibles else ""),
        ]


def recolter(reg: Registre, audits: List[List[Dict[str, str]]], *,
             normaliser: Callable[[str], str],
             est_blanc: Callable[[str], bool],
             liste_noire: Set[str],
             est_courant: Callable[[str], bool],
             deriver: Callable[[str], Set[str]],
             tous_types: bool = False,
             date: Optional[str] = None,
             bilan: Optional[Bilan] = None) -> Bilan:
    """Ajoute au registre (en mémoire) ce que les audits ont masqué. Rend les COMPTES.

    Gardes : jamais un terme de moins de 3 lettres ; jamais un terme dont TOUS les mots sont des mots
    courants (« sommeil », « Fort heureusement ») ; jamais un terme écrit tout en minuscules à chacune
    de ses occurrences, sans chiffre ni @ (un nom propre porte une majuscule). Ces deux derniers sont
    comptés comme SUSPECTS, jamais affichés."""
    b = bilan or Bilan()
    date = date or datetime.date.today().isoformat()
    b.registre_avant = len(reg.entrees)
    b.lignes_illisibles = reg.illisibles
    noire = {normaliser(n) for n in liste_noire}

    index: Dict[str, Entree] = {}
    for e in reg.entrees:
        index.setdefault(normaliser(e.entree), e)
        for v in e.variantes:
            index.setdefault(normaliser(v), e)

    formes: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    types: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    majuscule: Dict[str, bool] = collections.defaultdict(bool)
    for lignes in audits:
        b.audits += 1
        for l in lignes:
            b.lignes_audit += 1
            texte = l.get("text") or ""
            t = (l.get("entity_type") or "").strip() or "INCONNU"
            src = (l.get("source") or "").strip()
            if src in SOURCES_PERMANENTES:
                b.deja_permanents += 1
                continue
            if t in TYPES_REGLES and not tous_types:
                b.types_regles += 1
                continue
            forme = _affichage(texte)
            cle = normaliser(forme)
            if not cle:
                continue
            formes[cle][forme] += 1
            types[cle][t] += 1
            if any(c.isupper() for c in forme) or any(c.isdigit() for c in forme) or "@" in forme:
                majuscule[cle] = True

    b.termes_distincts = len(formes)

    def garde(forme: str) -> Optional[str]:
        if _lettres(forme) < LETTRES_MIN:
            return "court"
        if len(forme.split()) > MOTS_MAX or len(forme) > CARACTERES_MAX:
            return "long"
        mots = _mots(forme)
        if mots and all(est_courant(m) for m in mots) and not any(c.isdigit() for c in forme):
            return "courant"
        return None

    # Du plus long au plus court : un nom composé passe avant ses morceaux, qui y deviennent variantes.
    ordre = sorted(formes, key=lambda k: (-len(k), k))
    for cle in ordre:
        forme = max(formes[cle].items(), key=lambda kv: (kv[1], kv[0]))[0]
        if est_blanc(forme):
            b.liste_blanche += 1
            continue
        if cle in noire:
            b.liste_noire += 1
            continue
        if cle in index:
            b.deja_au_registre += 1
            continue
        g = garde(forme)
        if g == "court":
            b.trop_courts += 1
            continue
        if g == "long":
            b.trop_longs += 1
            continue
        if g == "courant":
            b.suspects_mot_courant += 1
            continue
        if not majuscule[cle]:
            b.suspects_minuscules += 1
            continue
        variantes = []
        for v in sorted(deriver(forme), key=lambda s: (-len(s), s)):
            kv = normaliser(v)
            if not kv or kv == cle or kv in index or kv in noire or est_blanc(v) \
                    or any(normaliser(x) == kv for x in variantes):
                continue
            if garde(v) is not None:
                b.variantes_ecartees += 1
                continue
            variantes.append(v)
        typ = types[cle].most_common(1)[0][0]
        e = Entree(date, typ, forme, variantes)
        reg.lignes.append(e)
        index[cle] = e
        for v in variantes:
            index[normaliser(v)] = e
        b.nouvelles_entrees += 1
        b.nouvelles_variantes += len(variantes)

    b.registre_apres = len(reg.entrees)
    return b

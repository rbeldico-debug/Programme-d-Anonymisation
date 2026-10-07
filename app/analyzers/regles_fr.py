"""Règles françaises qui passent AVANT le LLM : NIR, RPPS/ADELI, dates en toutes lettres, voies
(Unicode), courriels SANS RÉSEAU, et repérage des éponymes médicaux.

Pourquoi en Python et pas dans config.yaml : Presidio applique à toute règle du YAML les drapeaux
DOTALL | MULTILINE | IGNORECASE, ce qui interdit d'exiger une majuscule (voies) ; et une règle du
YAML ne voit pas son CONTEXTE (NIR sans clé, RPPS). Chaque reconnaisseur se teste seul, sans spaCy
ni moteur : `Reco().analyze(texte, [entité])`.

Constat qui a motivé ce module (banc PDF synthétique du 07/10/2026, couche Presidio seule) :
NIR 23/24 fuites, RPPS 29/32, dates en lettres 28/32, « [MASQUÉ]ève-Haute » (regex de voie ASCII),
102/116 éponymes proposés comme noms.
"""
import re
import unicodedata

import tldextract
import tldextract.tldextract as _tld_module
from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import EmailRecognizer


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


class _RecoRegex(EntityRecognizer):
    """Base : une regex compilée, un score décidé par `noter(texte, m)` (None = rejeté)."""
    ENTITE = None
    REGEX = None

    def __init__(self, supported_language="fr"):
        super().__init__(supported_entities=[self.ENTITE], supported_language=supported_language,
                         name=self.__class__.__name__)

    def load(self):
        pass

    def noter(self, texte, m):
        return 1.0

    def empan(self, m):
        return m.start(), m.end()

    def analyze(self, text, entities, nlp_artifacts=None, **kwargs):
        if entities and self.ENTITE not in entities:
            return []
        resultats = []
        for m in self.REGEX.finditer(text):
            score = self.noter(text, m)
            if score is None:
                continue
            debut, fin = self.empan(m)
            resultats.append(RecognizerResult(
                entity_type=self.ENTITE, start=debut, end=fin, score=score,
                recognition_metadata={RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                                      RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id}))
        return resultats


def _contexte_avant(texte, debut, motif, largeur=60):
    """Le motif apparaît-il dans les `largeur` caractères qui précèdent (sans accents, minuscules) ?"""
    avant = _sans_accents(texte[max(0, debut - largeur):debut]).lower()
    return motif.search(avant) is not None


# --------------------------------------------------------------------------------------------- NIR
# 1 sexe (1/2 ; 3/4 et 7/8 : immatriculations provisoires) · 2 année · 2 mois (01-12, ou 20 et
# 30-99 : mois inconnu ou fictif) · 2 département (2A/2B pour la Corse) · 3 commune · 3 ordre · 2 clé.
# Séparateurs admis entre les groupes : espace, point, tiret, et UNE coupure de ligne (NIR coupé en
# fin de ligne, « > » d'une citation Markdown compris).
_SEP = r"(?:[ \t.\-]{0,2}(?:\r?\n[ \t>]*)?)"
_NIR = re.compile(
    r"(?<![\dA-Za-z])"
    r"(?P<sexe>[123478])" + _SEP +
    r"(?P<annee>\d{2})" + _SEP +
    r"(?P<mois>0[1-9]|1[0-2]|[2-9]\d)" + _SEP +
    r"(?P<dep>\d{2}|2[ABab])" + _SEP +
    r"(?P<commune>\d{3})" + _SEP +
    r"(?P<ordre>\d{3})"
    r"(?:(?:[ \t,]*(?i:cl[ée]f?)[ \t]*:?[ \t]*|" + _SEP + r")(?P<cle>\d{2}))?"   # « … 456 clé 42 » (dictée)
    r"(?![\d])")
_NIR_CONTEXTE = re.compile(
    r"\bnir\b|insee|securite\s+sociale|\bsecu\b|n[°o]\s*(?:de\s+)?s\.?\s?s\b|\bnss\b|immatricul|"
    r"\bassure(?:e|s|es)?\b|carte\s+vitale|inscription|matricule")


def cle_nir(treize_chiffres: str) -> int:
    """Clé de contrôle : 97 - (NIR mod 97) ; pour la Corse, 2A compte 19 et 2B compte 18."""
    s = treize_chiffres.upper().replace("2A", "19").replace("2B", "18")
    return 97 - (int(s) % 97)


class RecoNIR(_RecoRegex):
    """NIR (n° de sécurité sociale).
    - 15 caractères, clé JUSTE : 1,0.
    - 15 caractères, clé FAUSSE : quand même masqué (0,6 ; 0,85 avec contexte). Une clé fausse est
      d'abord une faute de frappe ou d'OCR, et 13 chiffres justes sur 15 identifient encore. Prix
      mesuré : aucun nombre de 15 chiffres à structure de NIR ailleurs dans les corpus synthétiques.
    - 13 caractères SANS clé : seulement avec contexte (« NIR », « sécurité sociale », « n° SS »…),
      sinon rejeté : un code CIP13 de médicament (3400936403114) a exactement la structure d'un NIR
      sans clé (sexe 3, mois 09)."""
    ENTITE = "FR_SSN"
    REGEX = _NIR

    def noter(self, texte, m):
        contexte = _contexte_avant(texte, m.start(), _NIR_CONTEXTE)
        corps = "".join(m.group(g) for g in ("sexe", "annee", "mois", "dep", "commune", "ordre"))
        if m.group("cle") is None:
            return 0.8 if contexte else None
        if cle_nir(corps) == int(m.group("cle")):
            return 1.0
        return 0.85 if contexte else 0.6


# ------------------------------------------------------------------------------------- RPPS, ADELI
_RPPS_CONTEXTE = re.compile(r"\brpps\b|\badeli\b|identifiant\s+national|\bid\s+nat")


class RecoRPPS(_RecoRegex):
    """RPPS : 11 chiffres commençant par 10 (« 8 » devant = identifiant national e-CPS).
    - forme 10xxxxxxxxx (ou 810xxxxxxxxx) d'un seul tenant : masquée même sans contexte (0,6) ;
    - avec « RPPS » / « ADELI » / « identifiant national » juste avant : TOUT numéro de 9 à 12
      chiffres (espaces ou points admis) est masqué — un RPPS mal recopié, un ADELI (9 chiffres)."""
    ENTITE = "FR_RPPS"
    REGEX = re.compile(r"(?<![\d.])(?:\d[ .]?){8,11}\d(?![\d])")

    def noter(self, texte, m):
        # contexte JUSTE avant : rien qui ressemble à un chiffre entre le mot et le numéro
        # (« RPPS 99000261629 — Tél. 03 53… » : le téléphone n'est pas un RPPS)
        avant = _sans_accents(texte[max(0, m.start() - 30):m.start()]).lower()
        mots = list(_RPPS_CONTEXTE.finditer(avant))
        if mots and not re.search(r"\d", avant[mots[-1].end():]):
            return 1.0
        if re.fullmatch(r"8?10\d{9}", m.group()):
            return 0.6
        return None


# ------------------------------------------------------------------------ dates en toutes lettres
_UNITES = (r"dix-sept|dix-huit|dix-neuf|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|"
           r"douze|treize|quatorze|quinze|seize|vingts?|trente|quarante|cinquante|soixante")
_NOMBRE = rf"(?:{_UNITES})(?:(?:[ -]et[ -]|[ -])(?:{_UNITES})){{0,4}}"
_JOUR_L = (r"premier|1er|trente[ -]et[ -]un|trente|vingt[ -]et[ -]un|"
           r"vingt-(?:deux|trois|quatre|cinq|six|sept|huit|neuf)|"
           r"dix-sept|dix-huit|dix-neuf|vingt|onze|douze|treize|quatorze|quinze|seize|"
           r"deux|trois|quatre|cinq|six|sept|huit|neuf|dix")
_JOUR = rf"(?:{_JOUR_L}|0?[1-9]|[12]\d|3[01])"
_MOIS = (r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|"
         r"d[ée]cembre|(?:janv|f[ée]vr?|avr|juil|sept|oct|nov|d[ée]c)(?:\.|(?=\s+(?:19|20)\d{2}\b)))")
_ANNEE = (rf"(?:(?:19|20)\d{{2}}(?!\d)|"
          rf"(?:deux[ -]mille|mil(?:le)?[ -]neuf[ -]cents?|dix[ -]neuf[ -]cents?)(?:[ -]{_NOMBRE})?)")
_DATE_L = re.compile(
    rf"(?<![\w-])(?:{_JOUR}\s+au\s+)?{_JOUR}\s+{_MOIS}(?:\s+{_ANNEE})?(?![\w-])",
    re.IGNORECASE)


class RecoDateLettres(_RecoRegex):
    """« douze mars deux mille vingt-quatre », « 1er avril », « 12 janv. 2024 », « le 3 avril ».
    Un JOUR est exigé (politique du dépôt : « mars 2024 » seul n'est pas masqué). Une durée
    (« trois mois », « deux ans ») ne contient pas de nom de mois : elle ne correspond jamais."""
    ENTITE = "DATE"
    REGEX = _DATE_L


# ----------------------------------------------------------------------------- voies (Unicode)
_TYPES_VOIE = (r"rue|avenue|av\.|boulevard|bd|impasse|all[ée]e|quai|place|route|chemin|cours|square|"
               r"esplanade|passage|cit[ée]|r[ée]sidence|lotissement|lieu-dit|faubourg|rond-point|"
               r"sentier|hameau|chauss[ée]e|promenade|parvis|ruelle|venelle|traverse|mont[ée]e")
_LIEN = r"(?:de[ \t]+la|du|des|de|la|le|les|aux|à[ \t]+la|au|sur|sous|et)"
_ELIDE = r"(?:de[ \t]+l|à[ \t]+l|d|l)['’]"               # « de l’Abbé », « d’Estienne » : sans espace
_MAJ = r"(?:[A-ZÀ-ÖØ-Þ][\w’'-]*|\d{1,4}(?:er)?(?!\d))"        # mot à majuscule, ou « 8 Mai », « 11 Novembre »
_MOT = r"[^\W\d_][\w’'-]*"                               # n'importe quel mot (après un numéro de voie)
_H = r"[ \t]+"                                           # jamais à travers une ligne
_PREFIXE = rf"(?:(?i:{_LIEN}){_H}|(?i:{_ELIDE}))?"
_VOIE = re.compile(
    rf"(?P<num>(?<![\d,.])\d{{1,4}}(?:[ \t]?(?:bis|ter|quater|[A-Da-d])\b)?,?{_H})?"
    rf"(?P<type>\b(?i:{_TYPES_VOIE})(?![\w-])){_H}"
    rf"{_PREFIXE}(?:{_MAJ}|(?P<min>{_MOT}))"
    rf"(?:{_H}{_PREFIXE}(?:{_MAJ}|{_MOT})){{0,4}}")


class RecoVoie(_RecoRegex):
    """Une voie : « 36 chemin de la Grève-Haute », « rue de l’Abbé-Fringant », « place du 8 Mai ».
    Remplace « VoirieFrance » (ASCII : « Grève-Haute » sortait « [MASQUÉ]ève-Haute », et l’apostrophe
    courbe coupait le nom ; elle traversait aussi les fins de ligne).
    Garde-fou : SANS numéro devant, le premier mot du nom doit porter une majuscule (« mise en place
    d'un traitement », « au cours de la journée », « à mi-chemin » ne sont pas des voies) ; AVEC
    numéro, un nom en minuscules est admis. Jamais à travers une ligne ; 5 mots de nom au plus, et
    les mots en minuscules en queue sont retirés (« … Grève-Haute depuis » -> « … Grève-Haute »)."""
    ENTITE = "LOCATION"
    REGEX = _VOIE

    def noter(self, texte, m):
        if m.group("num") is None and m.group("min") is not None:
            return None
        return 0.6

    def empan(self, m):
        # Mots de queue en minuscules retirés dès que le nom porte une majuscule (« rue Pasteur et
        # il » -> « rue Pasteur ») ; un nom tout en minuscules (après un numéro) est gardé entier.
        nom = list(re.finditer(r"\S+", m.string[m.end("type"):m.end()]))
        if any(re.match(r"[A-ZÀ-Þ\d]", w.group()) for w in nom):
            while nom and not re.match(r"[A-ZÀ-Þ\d]", nom[-1].group()):
                nom.pop()
            return m.start(), m.end("type") + nom[-1].end()
        return m.start(), m.end()


class RecoCodePostalVille(_RecoRegex):
    """« 54700 Pont-à-Mousson », « 54500 Vandœuvre-lès-Nancy », « 57000 Metz Cedex 1 » : la commune
    qui suit un code postal sur la même ligne. L'ancienne « VoirieFrance » masquait ces villes PAR
    ACCIDENT, en débordant de la ligne de la voie sur celle du code postal ; sans ce reconnaisseur,
    la corriger faisait fuir 2 villes de plus sur le banc (spaCy ne les voit pas)."""
    ENTITE = "LOCATION"
    # UN seul mot de commune (les noms officiels sont à traits d'union : « Saint-Dié-des-Vosges »),
    # précédé au besoin d'un article (« Le Havre », « L’Isle-Adam ») et suivi au besoin de « Cedex 1 ».
    # Jamais plus : en mode PDF les lignes sont jointes par une espace, et « Pont-à-Mousson Objet »
    # masquait « Objet », le premier mot de la ligne suivante.
    REGEX = re.compile(
        r"(?<![\d\w])\d{5}[ \t]+(?P<ville>(?:(?P<art>Le|La|Les)[ \t]+|L['’])?"
        r"[A-ZÀ-ÖØ-Þ][\w’']*(?:-[\w’']+)*(?:[ \t]+(?i:cedex)(?:[ \t]+\d{1,2})?)?)")
    # un nombre de 5 chiffres suivi d'un mot-outil n'est pas un code postal suivi d'une commune
    # (« IPP 54012 Le patient » : « Le » deviendrait un secret, masqué PARTOUT en passe 2)
    MOTS_OUTILS = {"le", "la", "les", "l", "un", "une", "il", "elle", "ils", "elles", "on", "ce", "cet",
                   "cette", "mais", "et", "ou", "en", "au", "aux", "du", "des", "de", "d", "dans", "pour",
                   "par", "sur", "avec", "sans", "se", "sa", "son", "ses", "nous", "vous", "je", "tu",
                   "mme", "m", "mr", "dr", "pr", "patient", "patiente", "dossier", "tel", "tél"}

    def noter(self, texte, m):
        ville = m.group("ville")
        if m.group("art") or re.match(r"L['’][A-ZÀ-Þ]", ville):
            return 0.6
        return None if re.split(r"[\s’'.-]", ville)[0].lower() in self.MOTS_OUTILS else 0.6

    def empan(self, m):
        return m.start("ville"), m.end("ville")


# ----------------------------------------------------------------------- courriels SANS RÉSEAU
# tldextract, par défaut, TÉLÉCHARGE la liste publicsuffix.org quand son cache est vide (constaté :
# ~/.cache/python-tldextract/…/urls/ rempli le 05/10/2026 à 22 h 05). Ici : liste EMBARQUÉE du paquet,
# aucune URL, aucun cache sur disque. Le global du module est remplacé aussi, pour tout autre appelant.
EXTRACTEUR_HORS_LIGNE = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=(), fallback_to_snapshot=True)
_tld_module.TLD_EXTRACTOR = EXTRACTEUR_HORS_LIGNE


class EmailHorsLigne(EmailRecognizer):
    def validate_result(self, pattern_text: str):
        return EXTRACTEUR_HORS_LIGNE(pattern_text).fqdn != ""


def reconnaisseurs(langue="fr"):
    return [RecoNIR(langue), RecoRPPS(langue), RecoDateLettres(langue), RecoVoie(langue),
            RecoCodePostalVille(langue),
            EmailHorsLigne(supported_language=langue)]


# ------------------------------------------------------------------------------ éponymes médicaux
# Un éponyme n'est écarté de l'amorce QUE dans son contexte médical (« échelle de Hamilton »,
# « maladie de Parkinson », « MMSE de Folstein »), occurrence par occurrence. « M. Hamilton » reste
# un candidat, et un nom retenu ailleurs est masqué PARTOUT (passe 2 : y compris dans l'échelle).
# Deux familles, chacune avec SES déclencheurs : « maladie de Beck » ou « maladie de Dubois » ne
# sont PAS des éponymes (Beck et Dubois sont des échelles), donc pas écartés.
EPONYMES_CLINIQUES = {
    "alzheimer", "parkinson", "huntington", "creutzfeldt", "jakob", "lewy", "pick", "binswanger",
    "korsakoff", "wernicke", "charcot", "marie", "tooth", "cotard", "capgras", "fregoli", "ganser",
    "asperger", "tourette", "gilles", "kanner", "rett", "down", "turner", "klinefelter", "crohn",
    "basedow", "hashimoto", "cushing", "addison", "raynaud", "guillain", "barré", "barre",
    "horton", "willis", "broca", "babinski", "lasègue", "lasegue", "romberg", "korsakov",
}
EPONYMES_ECHELLES = {
    "hamilton", "beck", "folstein", "stroop", "rey", "wechsler", "raven", "rorschach", "montgomery",
    "asberg", "åsberg", "young", "bech", "rafaelsen", "zung", "spielberger", "covi", "hoehn", "yahr",
    "grober", "buschke", "mattis", "benton", "dubois", "hachinski", "zarit", "conners", "hare",
    "rosenberg", "pittsburgh", "epworth", "fagerström", "fagerstrom", "glasgow", "taylor", "osterrieth",
}
# Morceaux qui ne valent éponyme qu'à l'intérieur d'un nom composé (« Charcot-Marie-Tooth »,
# « Creutzfeldt-Jakob », « Gilles de la Tourette ») : « la maladie de Marie » reste un candidat.
COMPOSANTS_SEULEMENT = {"marie", "tooth", "jakob", "gilles", "barré", "barre", "yahr", "rafaelsen"}
_FIN = r"(?:[ \t]+[^\s.;:]+){0,3}?[ \t]+(?:(?:de|du|des|type)[ \t]+|d['’])$"   # « démence de type Alzheimer »
_DECL_CLINIQUE = re.compile(
    r"\b(?:maladie|syndrome|chor[ée]e|d[ée]mence|corps|signe|man[œo]euvre|aphasie|enc[ée]phalopathie|"
    r"psychose|thyro[ïi]dite|ph[ée]nom[èe]ne|d[ée]lire|stade)s?" + _FIN, re.IGNORECASE)
_DECL_ECHELLE = re.compile(
    r"\b(?:[ée]chelle|test|inventaire|questionnaire|auto-questionnaire|score|classification|crit[èe]res|"
    r"[ée]preuve|figure|batterie|matrices|indice|m[ée]thode|grille|stade|mmse|madrs|hdrs|ham-[ad]|bdi|"
    r"ymrs|stai|mots)s?" + _FIN, re.IGNORECASE)


def eponyme_en_contexte(texte: str, debut: int, fin: int) -> bool:
    """Le candidat texte[debut:fin] est-il un éponyme médical EMPLOYÉ COMME TEL ?
    Tous ses mots à majuscule doivent appartenir à UNE famille (cliniques ou échelles), et un
    déclencheur de cette famille (« maladie de », « échelle de dépression de », « MMSE de »…) doit le
    précéder dans la même phrase, au plus 3 mots avant le « de »."""
    candidat = texte[debut:fin].strip()
    morceaux = [p.lower() for w in re.findall(r"[^\W\d_][\w’'-]*", candidat) if w[0].isupper()
                for p in re.split(r"[-’']", w) if p]
    if not morceaux:
        return False
    if len(morceaux) == 1 and morceaux[0] in COMPOSANTS_SEULEMENT:
        return False
    if not _en_contexte(texte, debut, morceaux):
        return False
    # Le même mot employé AILLEURS sur la page hors de tout contexte d'éponyme (« Mme Beck décrit… »)
    # garde le candidat : la contre-épreuve du 07/10 a montré que spaCy peut ne voir le nom du patient
    # que sous une autre forme (« Odile Beck »), et que c'était l'éponyme qui masquait « Mme Beck ».
    for w in set(re.findall(r"[^\W\d_][\w’'-]*", candidat)):
        if not w[0].isupper():
            continue
        for m in re.finditer(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", texte):
            if not (debut <= m.start() < fin) and not _en_contexte(texte, m.start(), [w.lower()]):
                return False
    return True


def _en_contexte(texte, debut, morceaux):
    avant = re.split(r"[.;:\n]", texte[max(0, debut - 80):debut])[-1]
    for famille, declencheur in ((EPONYMES_CLINIQUES, _DECL_CLINIQUE), (EPONYMES_ECHELLES, _DECL_ECHELLE)):
        if all(p in famille for p in morceaux) and declencheur.search(avant):
            return True
    return False

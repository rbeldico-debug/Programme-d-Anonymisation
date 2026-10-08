#!/usr/bin/env python3
"""Le REGISTRE des entrées masquées — « un mot qui a été masqué doit l'être pour toujours ».

Après une passe, au bureau, le coffre monté :

    .venv/bin/python outils/registre.py recolter <dossier de sortie> [<autre dossier>…]
    .venv/bin/python outils/registre.py recolter --a-blanc <dossier>     # compte sans rien écrire
    .venv/bin/python outils/registre.py etat                             # comptes du registre

Le dossier des dictionnaires est ANONYMIZER_DICT_DIR (ou --dictionnaires) ; il est EXIGÉ : le registre
porte des noms en clair, il ne se crée jamais par défaut dans le dépôt. Les dossiers de sortie sont
parcourus en profondeur (tous les *_audit.csv).

Ce qui sort au terminal : des COMPTES, jamais un terme ni un nom de fichier — c'est ce qui peut
remonter au pupitre. Le détail se lit dans le registre lui-même (registre.tsv, dans le coffre).

Ce que la récolte fait, et ne fait pas : voir app/core/registre.py (format, gardes) et
app/core/mots_courants.py (la liste des mots courants). Elle n'efface RIEN : pour libérer un mot
(« sommeil »), on l'écrit dans whitelist.txt, qui l'emporte sur le registre à la passe suivante.
"""
import argparse
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = os.path.dirname(ICI)
sys.path.insert(0, DEPOT)

from app.core import registre as R  # noqa: E402
from app.core.filter_engine import normaliser_terme  # noqa: E402
from app.core.garde_lieu import verifier_lieu  # noqa: E402


def _listes(dossier):
    """Listes blanche et noire, lues SANS les créer (FilterEngine créerait des fichiers vides)."""
    def lire(nom):
        p = os.path.join(dossier, nom)
        if not os.path.exists(p):
            return set()
        with open(p, encoding="utf-8") as f:
            return {l.strip() for l in f if l.strip() and not l.strip().startswith("#")}
    blanche = {normaliser_terme(w) for w in lire("whitelist.txt")} - {""}
    noire = lire("blacklist.txt")
    return blanche, noire


def _dossier_dictionnaires(a):
    d = a.dictionnaires or os.environ.get("ANONYMIZER_DICT_DIR")
    if not d:
        sys.exit("Erreur : ni --dictionnaires ni ANONYMIZER_DICT_DIR. Le registre porte des noms en clair :\n"
                 "il ne se crée jamais par défaut. Au bureau : "
                 "set -x ANONYMIZER_DICT_DIR ~/Scripts/Clinique/coffre/dictionnaires")
    d = os.path.abspath(os.path.expanduser(d))
    if os.path.commonpath([d, DEPOT]) == DEPOT:
        sys.exit("Erreur : le dossier des dictionnaires est DANS le dépôt de l'anonymiseur : refusé.")
    try:
        verifier_lieu(d, "des dictionnaires")
    except RuntimeError as e:
        sys.exit(f"Erreur : {e}")
    return d


def cmd_recolter(a):
    dico = _dossier_dictionnaires(a)
    if not os.path.isdir(dico):
        sys.exit("Erreur : le dossier des dictionnaires n'existe pas (le coffre est-il monté ?).")
    for s in a.sorties:
        if not os.path.exists(s):
            sys.exit("Erreur : un dossier de sortie donné n'existe pas.")
        try:
            verifier_lieu(s, "de sortie")
        except RuntimeError as e:
            sys.exit(f"Erreur : {e}")

    from app.core.mots_courants import MotsCourants
    mc = MotsCourants()
    blanche, noire = _listes(dico)
    chemin = os.path.join(dico, R.NOM_FICHIER)

    fichiers = R.fichiers_audit(a.sorties)
    if not fichiers:
        print("Aucun *_audit.csv dans le(s) dossier(s) donné(s) : rien à récolter.")
        print("(Une sortie produite avant le 08/10/2026 n'en a pas : voir outils/reconstruire_audits.py.)")
        return 2

    with R.Verrou(chemin):
        reg = R.lire(chemin)
        bilan = R.Bilan()
        audits = []
        for f in fichiers:
            try:
                audits.append(R.lire_audit(f))
            except Exception:
                bilan.audits_illisibles += 1
        R.recolter(reg, audits,
                   normaliser=normaliser_terme,
                   est_blanc=lambda t: normaliser_terme(t) in blanche,
                   liste_noire=noire,
                   est_courant=mc.est_courant,
                   deriver=R.variantes_de,
                   tous_types=a.tous_types,
                   bilan=bilan)
        if not a.a_blanc and (bilan.nouvelles_entrees or not os.path.exists(chemin)):
            R.ecrire(chemin, reg)

    print("=== RÉCOLTE DU REGISTRE (comptes seuls) ===" + ("  [À BLANC : rien écrit]" if a.a_blanc else ""))
    for l in bilan.lignes_comptes():
        print("   " + l)
    return 0


def cmd_etat(a):
    dico = _dossier_dictionnaires(a)
    chemin = os.path.join(dico, R.NOM_FICHIER)
    if not os.path.exists(chemin):
        print("Pas de registre dans ce dossier de dictionnaires.")
        return 0
    reg = R.lire(chemin)
    blanche, noire = _listes(dico)
    ents = reg.entrees
    nb_var = sum(len(e.variantes) for e in ents)
    libres = sum(1 for e in ents if normaliser_terme(e.entree) in blanche) + \
        sum(1 for e in ents for v in e.variantes if normaliser_terme(v) in blanche)
    import collections
    types = collections.Counter(e.type for e in ents)
    dates = collections.Counter(e.date for e in ents)
    print("=== REGISTRE (comptes seuls) ===")
    print(f"   entrées : {len(ents)} ; variantes : {nb_var} ; libérées par la liste blanche : {libres} ; "
          f"lignes illisibles : {reg.illisibles}")
    print("   types : " + " · ".join(f"{t} {n}" for t, n in types.most_common()))
    print("   récoltes : " + " · ".join(f"{d} {n}" for d, n in sorted(dates.items())))
    print(f"   liste blanche : {len(blanche)} ; liste noire : {len(noire)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recolter", help="ajoute au registre ce que les audits ont masqué")
    r.add_argument("sorties", nargs="+", help="dossier(s) de sortie d'une passe (parcourus en profondeur)")
    r.add_argument("--dictionnaires", help="dossier des listes (défaut : ANONYMIZER_DICT_DIR)")
    r.add_argument("--a-blanc", action="store_true", help="compter sans rien écrire")
    r.add_argument("--tous-types", action="store_true",
                   help="inscrire aussi dates, téléphones, NIR… (que les règles fixes retrouvent déjà)")
    r.set_defaults(f=cmd_recolter)
    e = sub.add_parser("etat", help="comptes du registre (aucun terme)")
    e.add_argument("--dictionnaires", help="dossier des listes (défaut : ANONYMIZER_DICT_DIR)")
    e.set_defaults(f=cmd_etat)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())

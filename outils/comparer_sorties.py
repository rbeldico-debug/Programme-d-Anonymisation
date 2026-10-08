#!/usr/bin/env python3
"""Comparer ce que deux passes ont masqué sur les MÊMES documents (ex. les expertises en PDF et en .md).

    .venv/bin/python outils/comparer_sorties.py --pdf <sortie PDF> --md <sortie .md> [--unite mots|termes]

Les audits <fichier>_audit.csv des deux dossiers sont appariés par le nom du document SANS extension
(« 2026-03-12 AB.pdf_audit.csv » avec « 2026-03-12 AB.md_audit.csv » ; casse et forme Unicode
ignorées). Pour chaque paire, on compare les ENSEMBLES de ce qui a été masqué, sous forme normalisée.

Unité de comparaison :
  - « mots » (défaut) : chaque passage masqué est coupé en mots (lettres et chiffres, 2 caractères au
    moins), casse repliée. Robuste au découpage : « Dr Jean Dupont » d'un côté, « Jean Dupont » + « Dr »
    de l'autre ne comptent pas comme une différence ; un mot masqué d'un seul côté, si ;
  - « termes » : le passage entier, normalisé (casse, apostrophes, ponctuation de bord).

Deux niveaux de sortie :
  1. au TERMINAL, des COMPTES seuls (à coller au pupitre) : paires, non appariés, indice de Jaccard
     (moyen, médian, minimal), unités propres à chaque côté, dont mots courants, et leurs types.
     AUCUN nom de fichier, AUCUN terme ;
  2. le DÉTAIL, paire par paire (les unités qui diffèrent, avec leur type et un repère « mot courant »),
     dans un fichier écrit DANS le dossier --pdf (donc dans le coffre), à lire soi-même.
"""
import argparse
import collections
import csv
import datetime
import os
import re
import statistics
import sys
import unicodedata

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))

from app.core.filter_engine import normaliser_terme  # noqa: E402

SUFFIXE = "_audit.csv"
NOM_DETAIL = "_comparaison-pdf-md.txt"
_MOT = re.compile(r"[^\W_]{2,}")


def cle_document(nom_audit: str) -> str:
    base = nom_audit[:-len(SUFFIXE)] if nom_audit.endswith(SUFFIXE) else nom_audit
    base = os.path.splitext(base)[0]
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", base)).strip().casefold()


def unites(texte: str, unite: str):
    if unite == "termes":
        t = normaliser_terme(texte)
        return [t] if t else []
    return [m.casefold() for m in _MOT.findall(unicodedata.normalize("NFC", texte or ""))]


def lire_audits(dossier: str, unite: str):
    """{clé: {unité: Counter(types)}}, et les comptes (illisibles, ambigus)."""
    par_cle, noms, illisibles = {}, collections.Counter(), 0
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(SUFFIXE):
            continue
        cle = cle_document(nom)
        noms[cle] += 1
        try:
            with open(os.path.join(dossier, nom), newline="", encoding="utf-8") as f:
                lignes = list(csv.DictReader(f))
        except Exception:
            illisibles += 1
            continue
        d = collections.defaultdict(collections.Counter)
        for l in lignes:
            t = (l.get("entity_type") or "").strip() or "INCONNU"
            for u in unites(l.get("text") or "", unite):
                d[u][t] += 1
        par_cle[cle] = (nom, d)
    ambigus = {c for c, n in noms.items() if n > 1}
    for c in ambigus:
        par_cle.pop(c, None)
    return par_cle, illisibles, len(ambigus)


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def comparer(pdf: dict, md: dict, est_courant=None):
    """Rend (comptes, détail par paire). Ne touche pas au disque."""
    cles = sorted(set(pdf) & set(md))
    paires = []
    for c in cles:
        (npdf, a), (nmd, b) = pdf[c], md[c]
        sa, sb = set(a), set(b)
        paires.append(dict(nom_pdf=npdf, nom_md=nmd, j=jaccard(sa, sb), communs=len(sa & sb),
                           seul_pdf={u: a[u].most_common(1)[0][0] for u in sorted(sa - sb)},
                           seul_md={u: b[u].most_common(1)[0][0] for u in sorted(sb - sa)}))
    js = [p["j"] for p in paires]
    courant = est_courant or (lambda u: False)
    comptes = dict(
        paires=len(paires),
        pdf_seuls=len(set(pdf) - set(md)), md_seuls=len(set(md) - set(pdf)),
        j_moyen=statistics.fmean(js) if js else None,
        j_median=statistics.median(js) if js else None,
        j_min=min(js) if js else None,
        identiques=sum(1 for j in js if j == 1.0),
        sous_05=sum(1 for j in js if j < 0.5),
        u_pdf=sum(len(p["seul_pdf"]) for p in paires),
        u_md=sum(len(p["seul_md"]) for p in paires),
        paires_pdf=sum(1 for p in paires if p["seul_pdf"]),
        paires_md=sum(1 for p in paires if p["seul_md"]),
        courants_pdf=sum(1 for p in paires for u in p["seul_pdf"] if courant(u)),
        courants_md=sum(1 for p in paires for u in p["seul_md"] if courant(u)),
        types_pdf=collections.Counter(t for p in paires for t in p["seul_pdf"].values()),
        types_md=collections.Counter(t for p in paires for t in p["seul_md"].values()),
        vides_pdf=sum(1 for c in cles if not pdf[c][1]), vides_md=sum(1 for c in cles if not md[c][1]),
    )
    return comptes, paires


def _f(x):
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def lignes_terminal(c, illisibles, ambigus, unite):
    t = lambda cnt: " · ".join(f"{k} {v}" for k, v in cnt.most_common()) or "aucun"
    return [
        f"=== COMPARAISON PDF / .md (comptes seuls ; unité : {unite}) ===",
        f"   paires appariées : {c['paires']} ; PDF sans pendant : {c['pdf_seuls']} ; .md sans pendant : {c['md_seuls']} ; "
        f"noms ambigus écartés : {ambigus} ; audits illisibles : {illisibles}",
        f"   audits sans aucun masque : {c['vides_pdf']} côté PDF, {c['vides_md']} côté .md",
        f"   Jaccard : moyen {_f(c['j_moyen'])} · médian {_f(c['j_median'])} · minimal {_f(c['j_min'])} ; "
        f"paires identiques {c['identiques']} ; sous 0,5 : {c['sous_05']}",
        f"   propres au PDF : {c['u_pdf']} (dans {c['paires_pdf']} paires), dont {c['courants_pdf']} mots courants",
        f"   propres au .md : {c['u_md']} (dans {c['paires_md']} paires), dont {c['courants_md']} mots courants",
        f"   types, propres au PDF : {t(c['types_pdf'])}",
        f"   types, propres au .md : {t(c['types_md'])}",
    ]


def ecrire_detail(chemin, paires, pdf, md, unite, est_courant=None):
    courant = est_courant or (lambda u: False)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"# Comparaison PDF / .md — {datetime.datetime.now():%Y-%m-%d %H:%M} — unité : {unite}\n")
        f.write("# CONTIENT DES TERMES EN CLAIR : reste dans le coffre, ne se colle pas au pupitre.\n")
        f.write("# Paires de la plus divergente à la plus proche. [type] = type lu dans l'audit ;"
                " (courant) = mot courant du français, candidat à la liste blanche.\n\n")
        for p in sorted(paires, key=lambda p: (p["j"], p["nom_pdf"])):
            f.write(f"{p['nom_pdf']}  <->  {p['nom_md']}\n")
            f.write(f"   Jaccard {p['j']:.2f} ; communs {p['communs']} ; PDF seul {len(p['seul_pdf'])} ; "
                    f".md seul {len(p['seul_md'])}\n")
            for titre, d in (("PDF seul", p["seul_pdf"]), (".md seul", p["seul_md"])):
                if d:
                    f.write(f"   {titre} : " + " ; ".join(
                        f"{u} [{t}]" + (" (courant)" if courant(u) else "") for u, t in d.items()) + "\n")
            f.write("\n")
        seuls_pdf = sorted(pdf[c][0] for c in set(pdf) - set(md))
        seuls_md = sorted(md[c][0] for c in set(md) - set(pdf))
        if seuls_pdf or seuls_md:
            f.write("# Sans pendant\n")
            for n in seuls_pdf:
                f.write(f"   PDF seulement : {n}\n")
            for n in seuls_md:
                f.write(f"   .md seulement : {n}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, chemin)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True, help="dossier de sortie de la passe PDF (ses *_audit.csv)")
    ap.add_argument("--md", required=True, help="dossier de sortie de la passe .md (ses *_audit.csv)")
    ap.add_argument("--unite", choices=("mots", "termes"), default="mots")
    ap.add_argument("--detail", help=f"fichier du détail (défaut : {NOM_DETAIL} dans le dossier --pdf)")
    ap.add_argument("--sans-mots-courants", action="store_true",
                    help="ne pas charger la liste des mots courants (fr_core_news_lg)")
    a = ap.parse_args(argv)

    from app.core.garde_lieu import verifier_lieu
    for d in (a.pdf, a.md):
        if not os.path.isdir(d):
            sys.exit("Erreur : un des deux dossiers n'existe pas.")
    detail = a.detail or os.path.join(a.pdf, NOM_DETAIL)
    try:
        verifier_lieu(os.path.dirname(os.path.abspath(detail)), "du détail")
    except RuntimeError as e:
        sys.exit(f"Erreur : {e}")

    est_courant = None
    if not a.sans_mots_courants:
        try:
            from app.core.mots_courants import MotsCourants
            est_courant = MotsCourants().est_courant
        except Exception:
            print("   (liste des mots courants indisponible : le compte « mots courants » vaudra 0)")

    pdf, ill_p, amb_p = lire_audits(a.pdf, a.unite)
    md, ill_m, amb_m = lire_audits(a.md, a.unite)
    if not pdf or not md:
        print("Aucun *_audit.csv d'un côté au moins : rien à comparer.")
        print("(Une sortie produite avant le 08/10/2026 n'en a pas : voir outils/reconstruire_audits.py.)")
        return 2
    comptes, paires = comparer(pdf, md, est_courant)
    for l in lignes_terminal(comptes, ill_p + ill_m, amb_p + amb_m, a.unite):
        print(l)
    ecrire_detail(detail, paires, pdf, md, a.unite, est_courant)
    print(f"   détail paire par paire : {NOM_DETAIL if not a.detail else 'fichier --detail'}"
          f"{' dans le dossier --pdf' if not a.detail else ''} (termes en clair : à lire au bureau)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

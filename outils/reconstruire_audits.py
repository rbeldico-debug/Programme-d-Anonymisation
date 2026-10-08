#!/usr/bin/env python3
"""Reconstruire les *_audit.csv d'une passe qui n'en a pas écrit, en comparant ENTRÉE et SORTIE.

Pourquoi : jusqu'au 08/10/2026 (branche « registre »), le pipeline ne remplissait jamais la liste des
détails — AUCUN *_audit.csv n'était écrit, quoi que dise la procédure. Les sorties de la passe du 07/10
n'en ont donc pas. Plutôt que de refaire des heures de passe avec le moteur, on retrouve ce qui a été
masqué en comparant chaque sortie à son entrée :
  - .md / .txt : la sortie est l'entrée où chaque terme masqué est devenu « [MASQUÉ] » ; on recale les
    morceaux restés en clair et ce qui manque entre eux est le terme masqué ;
  - .pdf : un mot de l'entrée absent de la sortie à la même place (même texte, même position) a été
    effacé par le masquage. Les mots effacés contigus d'une même ligne forment un terme.

Limites, dites franchement :
  - le TYPE n'est pas connu : entity_type vaut « INCONNU », source « RECONSTRUIT » ;
  - PDF : un mot à moitié masqué (« [MASQUÉ]ève-Haute ») est rendu ENTIER ;
  - .md : deux masques collés (« [MASQUÉ][MASQUÉ] ») donnent UN terme ; une sortie dont les dates ont
    été DÉCALÉES (--cle-patient) ou les métiers généralisés (--metiers) ne se recale pas : comptée
    « divergente », aucun audit écrit pour elle.
Une entrée modifiée depuis la passe donne aussi « divergente ».

    .venv/bin/python outils/reconstruire_audits.py --entree <dossier d'entrée> --sortie <dossier de sortie> [--texte]

Au terminal : des COMPTES seulement. Un audit existant n'est jamais écrasé sans --remplacer.
"""
import argparse
import csv
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))

MASQUE = "[MASQUÉ]"
EN_TETE = ["page", "text", "entity_type", "source", "score"]


def termes_texte(source: str, sortie: str):
    """Les passages de `source` remplacés par [MASQUÉ] dans `sortie`, dans l'ordre. None si la
    sortie ne se recale pas sur la source."""
    morceaux = sortie.split(MASQUE)
    if len(morceaux) == 1:
        return [] if source == sortie else None
    if not source.startswith(morceaux[0]):
        return None
    pos = len(morceaux[0])
    termes = []
    debut = pos
    n = len(morceaux) - 1
    for k in range(1, n + 1):
        m = morceaux[k]
        if k == n:
            fin = len(source) - len(m)
            if not source.endswith(m) or fin <= debut:
                return None
            termes.append(source[debut:fin])
            break
        if m == "":
            continue  # deux masques collés : un seul passage
        j = source.find(m, debut + 1)
        if j < 0:
            return None
        termes.append(source[debut:j])
        debut = j + len(m)
    return termes


def termes_pdf(entree: str, sortie: str, tolerance: float = 0.6):
    """[(page 1-based, terme)] : mots de l'entrée absents de la sortie à la même place. None si les
    deux documents n'ont pas le même nombre de pages."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    a, b = fitz.open(entree), fitz.open(sortie)
    try:
        if len(a) != len(b):
            return None
        res = []
        for i in range(len(a)):
            restes = {}
            for w in b[i].get_text("words"):
                restes.setdefault(w[4], []).append((w[0], w[1]))
            courant, cle_ligne, dernier = [], None, None
            for w in a[i].get_text("words"):
                x0, y0, texte, bloc, ligne, rang = w[0], w[1], w[4], w[5], w[6], w[7]
                garde = any(abs(x - x0) <= tolerance and abs(y - y0) <= tolerance for x, y in restes.get(texte, ()))
                if garde:
                    if courant:
                        res.append((i + 1, " ".join(courant)))
                        courant = []
                    continue
                if courant and ((bloc, ligne) != cle_ligne or rang != dernier + 1):
                    res.append((i + 1, " ".join(courant)))
                    courant = []
                courant.append(texte)
                cle_ligne, dernier = (bloc, ligne), rang
            if courant:
                res.append((i + 1, " ".join(courant)))
        return res
    finally:
        a.close()
        b.close()


def ecrire_audit(chemin: str, lignes):
    tmp = chemin + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EN_TETE)
        for page, texte in lignes:
            w.writerow([page, texte, "INCONNU", "RECONSTRUIT", ""])
    os.chmod(tmp, 0o600)
    os.replace(tmp, chemin)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entree", required=True, help="dossier d'entrée de la passe (les originaux)")
    ap.add_argument("--sortie", required=True, help="dossier de sortie de la passe (les audits y sont écrits)")
    ap.add_argument("--texte", action="store_true", help="passe en mode texte (.md, .txt)")
    ap.add_argument("--remplacer", action="store_true", help="réécrire un audit déjà présent")
    a = ap.parse_args(argv)

    from app.core.garde_lieu import verifier_lieu
    for d, role in ((a.entree, "d'entrée"), (a.sortie, "de sortie")):
        if not os.path.isdir(d):
            sys.exit(f"Erreur : le dossier {role} n'existe pas.")
        try:
            verifier_lieu(d, role)
        except RuntimeError as e:
            sys.exit(f"Erreur : {e}")

    ext = (".md", ".txt") if a.texte else (".pdf",)
    noms = sorted(f for f in os.listdir(a.sortie)
                  if f.lower().endswith(ext) and os.path.isfile(os.path.join(a.sortie, f)))
    c = dict(sorties=len(noms), ecrits=0, deja=0, sans_entree=0, divergents=0, termes=0, vides=0)
    for nom in noms:
        audit = os.path.join(a.sortie, nom + "_audit.csv")
        if os.path.exists(audit) and not a.remplacer:
            c["deja"] += 1
            continue
        src = os.path.join(a.entree, nom)
        if not os.path.isfile(src):
            c["sans_entree"] += 1
            continue
        if a.texte:
            with open(src, encoding="utf-8") as f:
                s = f.read()
            with open(os.path.join(a.sortie, nom), encoding="utf-8") as f:
                o = f.read()
            t = termes_texte(s, o)
            lignes = None if t is None else [(1, x) for x in t]
        else:
            try:
                lignes = termes_pdf(src, os.path.join(a.sortie, nom))
            except Exception:
                lignes = None
        if lignes is None:
            c["divergents"] += 1
            continue
        ecrire_audit(audit, lignes)
        c["ecrits"] += 1
        c["termes"] += len(lignes)
        c["vides"] += (not lignes)

    print("=== RECONSTRUCTION DES AUDITS (comptes seuls) ===")
    print(f"   sorties : {c['sorties']} ; audits écrits : {c['ecrits']} (dont {c['vides']} sans aucun masque) ; "
          f"déjà présents : {c['deja']}")
    print(f"   sans entrée correspondante : {c['sans_entree']} ; divergents (non recalés) : {c['divergents']} ; "
          f"passages masqués retrouvés : {c['termes']}")
    return 0 if not c["divergents"] else 1


if __name__ == "__main__":
    sys.exit(main())

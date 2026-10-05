import argparse
import os
import sys
from dotenv import load_dotenv
from app.core.batch_processor import BatchProcessor
from app.core.date_shifter import shift_days_from_key
from app.core.garde_lieu import verifier_lieu

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Medical PDF Anonymizer")

    parser.add_argument("--input", "-i", default="data/input", help="Dossier entrée")
    parser.add_argument("--output", "-o", default="data/output", help="Dossier sortie")
    parser.add_argument("--debug", action="store_true", help="Mode Debug (visuel)")
    parser.add_argument("--texte", action="store_true",
                        help="Mode texte : lit des .txt, écrit des .txt (termes remplacés par [MASQUÉ])")
    parser.add_argument("--cle-patient", default=None,
                        help="Mode texte : clé du patient. Les dates complètes sont DÉCALÉES d'un nombre de jours "
                             "constant dérivé de cette clé (même clé = même décalage) au lieu d'être masquées. "
                             "Un dossier = un patient.")
    parser.add_argument("--metiers", action="store_true",
                        help="Mode texte : généralise les métiers RARES ou identifiants par un lieu/une "
                             "institution (ex. « facteur d'orgues » -> « artisan »). Les métiers courants "
                             "(retraité, enseignant...) ne sont pas touchés. Un second appel LLM par bloc.")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Erreur: Dossier {args.input} introuvable.")
        return 2

    # Avant de lire quoi que ce soit : les documents ne quittent jamais le disque local (app/core/garde_lieu.py).
    try:
        verifier_lieu(args.input, "d'entrée")
        verifier_lieu(args.output, "de sortie")
    except RuntimeError as e:
        print(f"Erreur: {e}")
        return 2

    if args.cle_patient and not args.texte:
        print("Erreur: --cle-patient n'a de sens qu'avec --texte (un PDF se masque, il ne se réécrit pas).")
        return 2

    if args.metiers and not args.texte:
        print("Erreur: --metiers n'a de sens qu'avec --texte.")
        return 2

    try:
        shift_days = shift_days_from_key(args.cle_patient) if args.cle_patient else None
        processor = BatchProcessor(args.input, args.output, debug_mode=args.debug,
                                   text_mode=args.texte, shift_days=shift_days,
                                   generalize_metiers=args.metiers)
        failed = processor.run()
        # Code de sortie non nul dès qu'un fichier a échoué : un script appelant doit le voir.
        return 1 if failed else 0

    except KeyboardInterrupt:
        print("\nArrêt manuel.")
        return 130
    except Exception as e:
        print(f"\nErreur critique : {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

import argparse
import os
import sys
from dotenv import load_dotenv
from app.core.batch_processor import BatchProcessor

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Medical PDF Anonymizer")

    parser.add_argument("--input", "-i", default="data/input", help="Dossier entrée")
    parser.add_argument("--output", "-o", default="data/output", help="Dossier sortie")
    parser.add_argument("--debug", action="store_true", help="Mode Debug (visuel)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Erreur: Dossier {args.input} introuvable.")
        return 2

    try:
        processor = BatchProcessor(args.input, args.output, debug_mode=args.debug)
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

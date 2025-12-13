import argparse
import os
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
        return

    try:
        processor = BatchProcessor(args.input, args.output, debug_mode=args.debug)
        processor.run()

    except KeyboardInterrupt:
        print("\nArrêt manuel.")
    except Exception as e:
        print(f"\nErreur critique : {e}")


if __name__ == "__main__":
    main()
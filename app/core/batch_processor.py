import os
import csv
from typing import List
from tqdm import tqdm
from dataclasses import asdict
from app.core.pipeline import AnonymizationPipeline
from app.domain.models import PipelineResult


class BatchProcessor:
    """
    Gère le traitement d'un dossier complet de PDF.
    """

    def __init__(self, input_dir: str, output_dir: str, debug_mode: bool = False):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.debug_mode = debug_mode

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.pipeline = AnonymizationPipeline()

    def run(self):
        files = [f for f in os.listdir(self.input_dir) if f.lower().endswith(".pdf")]

        if not files:
            print("Aucun fichier PDF trouvé.")
            return

        print(f"--- Batch : {len(files)} fichiers (Debug={self.debug_mode}) ---")

        report_data = []

        for filename in tqdm(files, desc="Anonymisation"):
            in_path = os.path.join(self.input_dir, filename)
            out_path = os.path.join(self.output_dir, filename)

            # Appel Pipeline
            result_obj = self.pipeline.process_file(in_path, out_path, debug_mode=self.debug_mode)

            # Sauvegarde audit individuel (si succès)
            if result_obj.status == "SUCCESS" and result_obj.details:
                self._save_file_audit(result_obj)

            # Préparation rapport global (sans les détails trop lourds)
            res_dict = asdict(result_obj)
            del res_dict['details']
            report_data.append(res_dict)

        self._save_report(report_data)
        print("\n--- Terminé ---")

    def _save_report(self, data: List[dict]):
        report_path = os.path.join(self.output_dir, "_batch_report.csv")
        keys = ["file", "status", "entities_found", "error"]

        if not data:
            return

        with open(report_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(data)

    def _save_file_audit(self, result: PipelineResult):
        audit_filename = f"{result.file}_audit.csv"
        audit_path = os.path.join(self.output_dir, audit_filename)
        keys = ["page", "text", "entity_type", "source", "score"]

        with open(audit_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for detail in result.details:
                writer.writerow(asdict(detail))
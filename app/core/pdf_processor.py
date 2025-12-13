import fitz  # PyMuPDF
from typing import List, Dict, Any
import os


class PdfProcessor:
    """
    Responsable de la manipulation bas niveau des fichiers PDF.
    """

    def __init__(self, file_path: str):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Le fichier {file_path} est introuvable.")

        self.file_path = file_path
        self.doc = fitz.open(file_path)

    def get_text_and_coordinates(self) -> List[Dict[str, Any]]:
        extracted_data = []
        for page_num, page in enumerate(self.doc):
            words = page.get_text("words")
            for w in words:
                word_data = {
                    "page": page_num,
                    "text": w[4],
                    "bbox": fitz.Rect(w[0], w[1], w[2], w[3])
                }
                extracted_data.append(word_data)
        return extracted_data

    def apply_redactions(self, redaction_zones: List[Dict[str, Any]], output_path: str, debug_mode: bool = False):
        """
        Applique les masques ou le mode debug.
        """
        # Groupement par page
        redactions_by_page = {}
        for zone in redaction_zones:
            p_num = zone["page"]
            if p_num not in redactions_by_page:
                redactions_by_page[p_num] = []
            redactions_by_page[p_num].append(zone)

        # Application
        for page_num, zones in redactions_by_page.items():
            if page_num < len(self.doc):
                page = self.doc[page_num]

                for zone in zones:
                    bbox = zone["bbox"]
                    source = zone.get("source", "UNKNOWN")
                    entity_type = zone.get("type", "?")

                    if debug_mode:
                        # --- MODE DEBUG : Cadres colorés ---
                        # Rouge pour LLM, Bleu pour Presidio/Autre
                        color = (1, 0, 0) if "LLM" in source else (0, 0, 1)

                        shape = page.new_shape()
                        shape.draw_rect(bbox)
                        shape.finish(color=color, fill=color, fill_opacity=0.3, width=1.5)
                        shape.insert_text((bbox.x0, bbox.y0 - 2), f"{entity_type}", fontsize=5, color=color)
                        shape.commit()
                    else:
                        # --- MODE PROD : Masquage noir ---
                        page.add_redact_annot(bbox, fill=(0, 0, 0))

                # On applique physiquement la suppression seulement si pas en debug
                if not debug_mode:
                    page.apply_redactions()
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"   [PDF] Sauvegarde : {output_path}")

    def close(self):
        if self.doc:
            self.doc.close()
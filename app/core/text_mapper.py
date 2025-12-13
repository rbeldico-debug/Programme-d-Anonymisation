from typing import List, Dict, Any


class TextMapper:
    """
    V2 : Gère le mapping Page par Page.
    """

    def __init__(self, pdf_words: List[Dict[str, Any]]):
        self.pdf_words = pdf_words
        # On organise les mots par page pour un accès rapide
        self.words_by_page = {}
        for w in self.pdf_words:
            p = w["page"]
            if p not in self.words_by_page:
                self.words_by_page[p] = []
            self.words_by_page[p].append(w)

    def get_text_for_page(self, page_num: int) -> str:
        """Reconstruit le texte d'une seule page."""
        if page_num not in self.words_by_page:
            return ""

        page_words = self.words_by_page[page_num]
        # Trie par ordre de lecture naturel (haut en bas, gauche à droite)
        # Tri secondaire par x0, tri primaire par y0 (avec une tolérance de ligne)
        # Simplification ici : on garde l'ordre d'extraction de PyMuPDF
        text_parts = [w["text"] for w in page_words]
        return " ".join(text_parts)

    def get_total_pages(self) -> int:
        return max(self.words_by_page.keys()) + 1 if self.words_by_page else 0

    def get_bboxes_for_page(self, page_num: int, entities: List[Dict]) -> List[Dict[str, Any]]:
        """
        Convertit les entités trouvées SUR UNE PAGE en zones PDF.
        """
        if page_num not in self.words_by_page:
            return []

        page_words = self.words_by_page[page_num]

        # On doit reconstruire le texte temporaire pour avoir les bons index (start/end)
        # C'est une reconstruction locale identique à get_text_for_page
        full_text_page = ""
        local_map = []
        current_index = 0

        for w in page_words:
            t = w["text"]
            start = current_index
            end = current_index + len(t)
            local_map.append({
                "start": start,
                "end": end,
                "bbox": w["bbox"],
                "text": t
            })
            full_text_page += t + " "  # Le même séparateur que get_text_for_page
            current_index = end + 1  # +1 pour l'espace

        redaction_zones = []

        for entity in entities:
            e_start = entity["start"]
            e_end = entity["end"]

            for word_info in local_map:
                # Intersection
                if word_info["start"] < e_end and word_info["end"] > e_start:
                    redaction_zones.append({
                        "page": page_num,
                        "bbox": word_info["bbox"],
                        "type": entity["type"],
                        "source": entity.get("source", "UNKNOWN"),
                        "text_debug": word_info["text"]
                    })

        return redaction_zones
import os
import re
from app.core.pdf_processor import PdfProcessor
from app.analyzers.local_analyzer import LocalAnalyzer
from app.analyzers.LlmAnalyzer import LlmAnalyzer
from app.core.text_mapper import TextMapper
from app.domain.models import PipelineResult, RedactionDetail, AnonymizationCandidate
from app.core.filter_engine import FilterEngine


class AnonymizationPipeline:
    def __init__(self):
        print("   [Pipeline] Chargement des moteurs...")
        self.local_analyzer = LocalAnalyzer()
        self.llm_analyzer = LlmAnalyzer()
        self.filter_engine = FilterEngine()
        print("   [Pipeline] Prêt.")

    def process_file(self, input_path: str, output_path: str, debug_mode: bool = False) -> PipelineResult:
        file_name = os.path.basename(input_path)

        try:
            # 1. Extraction
            pdf_proc = PdfProcessor(input_path)
            pdf_words = pdf_proc.get_text_and_coordinates()
            mapper = TextMapper(pdf_words)
            num_pages = mapper.get_total_pages()

            print(f"   [Pipeline] Traitement de {file_name} ({num_pages} pages)...")
            all_redaction_zones = []

            # 2. Boucle Page par Page
            for page_num in range(num_pages):
                page_text = mapper.get_text_for_page(page_num)
                if not page_text or len(page_text.strip()) < 5:
                    continue

                # --- A. Génération des Candidats Initiaux ---
                # On commence avec les listes utilisateur
                candidates = self._generate_candidates_from_user_lists(page_text)

                # On ajoute les propositions de Presidio
                presidio_entities = self.local_analyzer.analyze_text(page_text)
                for ent in presidio_entities:
                    candidates.append(AnonymizationCandidate(
                        start=ent['start'], end=ent['end'],
                        entity_type=ent['type'], source='PRESIDIO',
                        text_slice=ent['text_slice']
                    ))

                # --- B. Le Jugement par le LLM ---
                final_entities_for_page = self.llm_analyzer.judge_candidates(page_text, candidates)

                # --- C. Mapping et Application ---
                zones_on_page = mapper.get_bboxes_for_page(page_num, final_entities_for_page)
                all_redaction_zones.extend(zones_on_page)

                print(
                    f"      -> Page {page_num + 1}: {len(candidates)} candidats -> {len(final_entities_for_page)} décisions finales.")

            # 3. Application sur le PDF
            pdf_proc.apply_redactions(all_redaction_zones, output_path, debug_mode=debug_mode)
            pdf_proc.close()

            # (Le code d'audit devra être adapté plus tard)
            return PipelineResult(
                file=file_name,
                status="SUCCESS",
                entities_found=len(all_redaction_zones)
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return PipelineResult(file=file_name, status="FAILED", error=str(e), entities_found=0)

    def _generate_candidates_from_user_lists(self, text: str) -> list[AnonymizationCandidate]:
        """Trouve les occurrences des listes utilisateur dans le texte."""
        candidates = []
        # Blacklist (ce sont des candidats à masquer)
        for term in self.filter_engine.blacklist:
            for match in re.finditer(re.escape(term), text, re.IGNORECASE):
                candidates.append(AnonymizationCandidate(
                    start=match.start(), end=match.end(),
                    entity_type='USER_DEFINED', source='USER_BLACKLIST',
                    text_slice=match.group()
                ))
        return candidates
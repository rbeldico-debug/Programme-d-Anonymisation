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
            # 1. Extraction Initiale
            pdf_proc = PdfProcessor(input_path)
            pdf_words = pdf_proc.get_text_and_coordinates()
            mapper = TextMapper(pdf_words)
            num_pages = mapper.get_total_pages()

            print(f"   [Pipeline] Analyse de {file_name} ({num_pages} pages)...")

            # --- PASSE 1 : DÉCOUVERTE GLOBALE ---
            global_secrets_to_hide = set()
            pages_text_cache = {}

            for page_num in range(num_pages):
                page_text = mapper.get_text_for_page(page_num)
                pages_text_cache[page_num] = page_text

                if not page_text or len(page_text.strip()) < 5: continue

                # A. SANCTION IMMÉDIATE (Hard Regex)
                # On ne demande PAS l'avis du LLM pour ça. C'est du masquage d'office.
                # (Assure-toi que tes patterns Presidio/Regex pour PHONE et DATE sont actifs)
                presidio_results = self.local_analyzer.analyze_text(page_text)

                soft_candidates_for_llm = set()

                for res in presidio_results:
                    entity_type = res['type']
                    text_slice = res['text_slice']

                    # LISTE ÉLARGIE DES TYPES "INDISCUTABLES"
                    # On ajoute "DATE" au cas où Spacy prend le dessus sur Presidio
                    if entity_type in ["PHONE_NUMBER", "EMAIL_ADDRESS", "FR_SSN", "DATE_TIME", "DATE"]:

                        # Vérification anti-bruit pour les dates (évite de masquer juste "2024")
                        if entity_type in ["DATE_TIME", "DATE"]:
                            # On ne garde que les dates longues (> 5 chars) ou contenant un "/"
                            if len(text_slice) < 6 and "/" not in text_slice:
                                continue

                        global_secrets_to_hide.add(text_slice.strip())

                # B. Validation LLM (Seulement pour les cas ambigus : Noms, Adresses)
                list_candidates = list(soft_candidates_for_llm)

                # On appelle le LLM seulement s'il reste des choses à vérifier ou si on veut qu'il trouve des NOUVEAUX trucs
                # Même si la liste est vide, on l'appelle pour qu'il trouve ce que Presidio a raté (ex: "Dr Rémy")
                final_terms = self.llm_analyzer.get_final_redaction_list(
                    page_text=page_text,
                    initial_candidates=list_candidates,
                    debug=debug_mode
                )

                for term in final_terms:
                    clean_term = term.strip()
                    if clean_term and clean_term.lower() not in self.filter_engine.whitelist:
                        global_secrets_to_hide.add(clean_term)

            print(
                f"   [Pipeline] Analyse terminée. {len(global_secrets_to_hide)} termes uniques identifiés pour suppression globale.")
            if debug_mode:
                print(f"   [Secrets] {global_secrets_to_hide}")

            # --- PASSE 2 : APPLICATION DES MASQUES PARTOUT ---
            all_redaction_zones = []

            # On parcourt à nouveau toutes les pages
            for page_num in range(num_pages):
                page_text = pages_text_cache.get(page_num, "")
                if not page_text: continue

                # On cherche CHAQUE secret global dans CETTE page
                for secret in global_secrets_to_hide:
                    # Recherche insensible à la casse pour maximiser la sécurité
                    # Utilisation de \b boundary seulement si le secret est un mot entier pour éviter de masquer "ass" dans "passer" ?
                    # Pour l'instant, recherche simple (plus sûr pour les adresses)
                    try:
                        for match in re.finditer(re.escape(secret), page_text, re.IGNORECASE):
                            fake_entity = {
                                "start": match.start(),
                                "end": match.end(),
                                "type": "GLOBAL_SECRET",
                                "source": "LLM_GLOBAL"
                            }
                            zones = mapper.get_bboxes_for_page(page_num, [fake_entity])
                            all_redaction_zones.extend(zones)
                    except Exception as e:
                        # Protection contre les regex invalides venant du LLM
                        print(f"   [Warn] Erreur regex sur le terme '{secret}': {e}")

            # 3. Application Physique sur le PDF
            pdf_proc.apply_redactions(all_redaction_zones, output_path, debug_mode=debug_mode)
            pdf_proc.close()

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
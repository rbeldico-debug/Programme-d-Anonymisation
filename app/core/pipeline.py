import os
import re
from app.core.pdf_processor import PdfProcessor
from app.analyzers.local_analyzer import LocalAnalyzer
from app.analyzers.LlmAnalyzer import LlmAnalyzer
from app.core.text_mapper import TextMapper
from app.domain.models import PipelineResult, RedactionDetail
from app.core.filter_engine import FilterEngine


class AnonymizationPipeline:
    def __init__(self):
        print("   [Pipeline] Chargement des modèles...")
        self.local_analyzer = LocalAnalyzer()
        self.llm_analyzer = LlmAnalyzer()
        self.filter_engine = FilterEngine()
        print("   [Pipeline] Prêt.")

    def process_file(self, input_path: str, output_path: str, debug_mode: bool = False) -> PipelineResult:
        file_name = os.path.basename(input_path)

        try:
            # 1. Extraction et Préparation
            pdf_proc = PdfProcessor(input_path)
            pdf_words = pdf_proc.get_text_and_coordinates()
            mapper = TextMapper(pdf_words)
            num_pages = mapper.get_total_pages()

            print(f"   [Pipeline] Traitement Global de {file_name} ({num_pages} pages)...")

            # --- STRUCTURES DE DONNÉES TEMPORAIRES ---
            # Pour stocker les résultats de l'IA par page (pour ne pas la relancer)
            pages_data = []
            # Le "Dictionnaire Global du Document" (ce qu'on va propager partout)
            global_sensitive_terms = set()

            # ====================================================
            # PASSE 1 : DÉCOUVERTE (Harvesting)
            # ====================================================
            print("      -> Passe 1 : Analyse IA et construction du dictionnaire...")
            for page_num in range(num_pages):
                page_text = mapper.get_text_for_page(page_num)

                # Si page vide, on garde une entrée vide
                if not page_text or len(page_text.strip()) < 5:
                    pages_data.append({"text": "", "entities": []})
                    continue

                # A. Détection Locale (Presidio + LLM)
                raw_entities = []

                # Presidio
                presidio_res = self.local_analyzer.analyze_text(page_text)
                for item in presidio_res:
                    item["source"] = "PRESIDIO"
                    raw_entities.append(item)

                # LLM
                llm_strings = self.llm_analyzer.analyze_text(page_text)
                llm_res = self._find_ranges_for_strings(page_text, llm_strings)
                for item in llm_res:
                    item["source"] = "LLM"
                    raw_entities.append(item)

                # B. Filtrage (Whitelist / Blacklist Utilisateur)
                # On applique déjà les règles utilisateur pour nettoyer
                clean_entities = self.filter_engine.apply_filters(page_text, raw_entities)

                # C. Alimentation du Dictionnaire Global
                # On ne stocke que les NOMS, EMAILS, ID pour la propagation
                # On évite de propager des dates ou des lieux communs
                types_to_propagate = ["PERSON", "EMAIL_ADDRESS", "FR_SSN", "PER", "ORG"]

                for ent in clean_entities:
                    if ent.get("type") in types_to_propagate:
                        txt = ent.get("text_slice", "").strip()
                        # Sécurité : pas de mots trop courts (ex: "M.")
                        if len(txt) > 3:
                            global_sensitive_terms.add(txt.lower())

                # On sauvegarde le travail pour la passe 2
                pages_data.append({
                    "text": page_text,
                    "entities": clean_entities
                })

            print(f"      -> Dictionnaire global construit : {len(global_sensitive_terms)} termes uniques identifiés.")
            # print(f"         Termes : {list(global_sensitive_terms)[:10]}...") # Debug

            # ====================================================
            # PASSE 2 : APPLICATION & PROPAGATION (Applying)
            # ====================================================
            print("      -> Passe 2 : Propagation et calcul des masques...")
            all_redaction_zones = []
            total_final_entities = 0
            audit_details = []

            for page_num in range(num_pages):
                p_data = pages_data[page_num]
                p_text = p_data["text"]
                if not p_text: continue

                # 1. On récupère les entités déjà trouvées localement (Date, Lieu, Nom local...)
                final_page_entities = p_data["entities"]

                # 2. RÉTRO-PROPAGATION (Le cœur de ta demande)
                # On cherche TOUS les termes du dictionnaire global dans CETTE page
                import re
                for term in global_sensitive_terms:
                    # Recherche insensible à la casse
                    # On utilise \b pour mot entier si possible, ou juste in string
                    # Ici on fait simple : recherche textuelle
                    if term in p_text.lower():
                        # On trouve les positions exactes
                        for match in re.finditer(re.escape(term), p_text, re.IGNORECASE):
                            # On ajoute cette nouvelle détection
                            # Note: Le TextMapper gérera les superpositions si le mot était déjà détecté localement
                            final_page_entities.append({
                                "type": "GLOBAL_PROPAGATION",
                                "start": match.start(),
                                "end": match.end(),
                                "score": 1.0,
                                "source": "GLOBAL_CONTEXT",  # Pour l'audit
                                "text_slice": match.group()
                            })

                # 3. Conversion en zones PDF (Mapping)
                # Note: On pourrait filtrer les doublons ici, mais get_bboxes gère bien ça
                zones_on_page = mapper.get_bboxes_for_page(page_num, final_page_entities)
                all_redaction_zones.extend(zones_on_page)

                total_final_entities += len(zones_on_page)

                # Prépare l'audit
                for z in zones_on_page:
                    audit_details.append(RedactionDetail(
                        page=z["page"],
                        text=z.get("text_debug", "N/A"),
                        entity_type=z.get("type", "?"),
                        source=z.get("source", "?"),
                        score=0.0
                    ))

            # 3. Application Finale sur le PDF
            pdf_proc.apply_redactions(all_redaction_zones, output_path, debug_mode=debug_mode)
            pdf_proc.close()

            return PipelineResult(
                file=file_name,
                status="SUCCESS",
                entities_found=total_final_entities,
                error=None,
                details=audit_details
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return PipelineResult(
                file=file_name,
                status="FAILED",
                entities_found=0,
                error=str(e)
            )

    def _find_ranges_for_strings(self, text: str, phrases: list) -> list:
        # (Inchangé)
        ranges = []
        for phrase in phrases:
            if not phrase: continue
            try:
                escaped_phrase = re.escape(phrase)
                for match in re.finditer(escaped_phrase, text, re.IGNORECASE):
                    ranges.append({
                        "type": "LLM_DETECTED",
                        "start": match.start(),
                        "end": match.end(),
                        "score": 1.0,
                        "text_slice": phrase
                    })
            except Exception:
                continue
        return ranges
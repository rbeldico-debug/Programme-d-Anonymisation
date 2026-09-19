import os
import re
from app.core.pdf_processor import PdfProcessor
from app.analyzers.local_analyzer import LocalAnalyzer
from app.analyzers.LlmAnalyzer import LlmAnalyzer, LlmIndisponibleError
from app.core.text_mapper import TextMapper
from app.domain.models import PipelineResult, RedactionDetail, AnonymizationCandidate
from app.core.filter_engine import FilterEngine
from app.core.date_shifter import shift_date_text

TEXT_MASK = "[MASQUÉ]"


class AnonymizationPipeline:
    def __init__(self):
        print("   [Pipeline] Chargement des moteurs...")
        self.local_analyzer = LocalAnalyzer()
        self.llm_analyzer = LlmAnalyzer()
        self.filter_engine = FilterEngine()
        print("   [Pipeline] Prêt.")

    def _collect_page_secrets(self, page_text: str, debug_mode: bool = False) -> set:
        """PASSE 1 sur une page : regex d'office puis LLM. Commun aux modes PDF et texte."""
        secrets = set()

        # A. SANCTION IMMÉDIATE (Hard Regex)
        # On ne demande PAS l'avis du LLM pour ça. C'est du masquage d'office.
        presidio_results = self.local_analyzer.analyze_text(page_text)

        soft_candidates_for_llm = set()

        for res in presidio_results:
            entity_type = res['type']
            text_slice = res['text_slice']

            # LISTE ÉLARGIE DES TYPES "INDISCUTABLES"
            if entity_type in ["PHONE_NUMBER", "EMAIL_ADDRESS", "FR_SSN", "DATE_TIME", "DATE"]:

                # Vérification anti-bruit pour les dates : jamais une année seule ("2024").
                # (L'ancien filtre « moins de 6 caractères sans "/" » jetait aussi « 3 mai ».)
                if entity_type in ["DATE_TIME", "DATE"] and text_slice.strip().isdigit():
                    continue

                secrets.add(text_slice.strip())

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
                secrets.add(clean_term)

        return secrets

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

                global_secrets_to_hide |= self._collect_page_secrets(page_text, debug_mode)

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

        except LlmIndisponibleError as e:
            # Panne du moteur : pas de trace Python (ce n'est pas un bug), mais un échec franc.
            print(f"   [Pipeline] ÉCHEC {file_name} : {e}")
            self._discard_output(input_path, output_path)
            return PipelineResult(file=file_name, status="FAILED", error=str(e), entities_found=0)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._discard_output(input_path, output_path)
            return PipelineResult(file=file_name, status="FAILED", error=str(e), entities_found=0)

    def process_text_file(self, input_path: str, output_path: str, debug_mode: bool = False,
                          shift_days: int = None) -> PipelineResult:
        """
        MODE TEXTE : lit un .txt, écrit un .txt. Les termes sont remplacés par [MASQUÉ].
        Si shift_days est donné, les dates COMPLÈTES sont décalées (format conservé) au lieu d'être masquées.
        """
        file_name = os.path.basename(input_path)

        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                text = f.read()

            chunks = self._split_text(text)
            print(f"   [Pipeline] Analyse de {file_name} ({len(chunks)} blocs)...")

            secrets = set()
            for chunk in chunks:
                if len(chunk.strip()) < 5: continue
                secrets |= self._collect_page_secrets(chunk, debug_mode)

            if debug_mode:
                print(f"   [Secrets] {secrets}")

            counter = {"masked": 0, "shifted": 0}

            def replace(match):
                if shift_days is not None:
                    shifted = shift_date_text(match.group(), shift_days)
                    if shifted:
                        counter["shifted"] += 1
                        return shifted
                counter["masked"] += 1
                return TEXT_MASK

            if secrets:
                # UNE seule passe, termes les plus longs d'abord : un remplacement n'est jamais re-remplacé
                ordered = sorted(secrets, key=len, reverse=True)
                pattern = re.compile("|".join(re.escape(term) for term in ordered), re.IGNORECASE)
                text = pattern.sub(replace, text)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"   [TXT] Sauvegarde : {output_path} ({counter['masked']} masques, {counter['shifted']} dates décalées)")

            return PipelineResult(file=file_name, status="SUCCESS",
                                  entities_found=counter["masked"] + counter["shifted"])

        except LlmIndisponibleError as e:
            print(f"   [Pipeline] ÉCHEC {file_name} : {e}")
            self._discard_output(input_path, output_path)
            return PipelineResult(file=file_name, status="FAILED", error=str(e), entities_found=0)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._discard_output(input_path, output_path)
            return PipelineResult(file=file_name, status="FAILED", error=str(e), entities_found=0)

    @staticmethod
    def _split_text(text: str, max_chars: int = 4000) -> list:
        """Découpe un texte en blocs de lignes entières (l'équivalent d'une page pour le LLM)."""
        chunks, current = [], ""
        for line in text.splitlines(keepends=True):
            if current and len(current) + len(line) > max_chars:
                chunks.append(current)
                current = ""
            current += line
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _discard_output(input_path: str, output_path: str):
        """Un fichier FAILED ne laisse AUCUN PDF en sortie (même pas celui d'une passe précédente)."""
        if os.path.abspath(output_path) != os.path.abspath(input_path) and os.path.exists(output_path):
            os.remove(output_path)
            print(f"   [Pipeline] Ancienne sortie supprimée : {output_path}")

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
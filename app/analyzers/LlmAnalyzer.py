import json
import re
from typing import List
from ollama import Client
from app.core.config_loader import ConfigLoader


class LlmIndisponibleError(RuntimeError):
    """Le moteur LLM n'a pas répondu : le document ne doit PAS sortir comme anonymisé."""


class LlmReponseTronqueeError(LlmIndisponibleError):
    """La réponse a buté sur la limite de longueur, deux fois (température du client, puis 0) :
    la liste est incomplète, le document ne doit PAS sortir comme anonymisé."""


# Balises de « pensée » : <think>…</think> (DeepSeek-R1, Qwen…) et <|channel>thought…<channel|>
# (Gemma 4). Le 05/10/2026, une pensée Gemma 4 coupée avant sa fin a rendu un contenu VIDE :
# 0 terme, document SUCCESS, nom en clair. Ces balises ne doivent jamais devenir des « termes ».
_OUVRANTES = ("<think>", "<|channel>")
_FERMANTES = ("</think>", "<channel|>")
_JETON_SPECIAL = re.compile(r"<\|[^<>\n]{0,40}>|<[^<>\n]{0,40}\|>")
# Puce, ou num\u00e9ro SUIVI D'UNE ESPACE : \u00ab 09.72.13.01.07 \u00bb et \u00ab 28.07.1965 \u00bb ne sont pas num\u00e9rot\u00e9s.
_PUCE = re.compile(r"^(?:[-*\u2022\u2013]+\s*|\d{1,3}[.)]\s+)")
_ENTETE = re.compile(r"^(?:r[ée]ponse(?:\s+attendue)?|ta\s+liste\s+finale[^:]*|termes?\s+[àa]\s+masquer)\s*:\s*",
                     re.IGNORECASE)
_RIEN = {"(rien)", "rien", "aucun", "aucune", "(aucun)", "(aucune)", "néant", "none"}


def nettoyer_reponse(brut: str) -> str:
    """Retire toute pensée de la réponse : bloc fermé, pensée déjà ouverte par le gabarit (on garde
    ce qui suit la DERNIÈRE balise fermante), pensée tronquée (tout ce qui suit une ouvrante sans
    fermante est jeté), et les jetons spéciaux résiduels (<turn|>, <|think|>…)."""
    texte = brut or ""
    for o, f in zip(_OUVRANTES, _FERMANTES):
        texte = re.sub(re.escape(o) + r".*?" + re.escape(f), "", texte, flags=re.DOTALL)
    for f in _FERMANTES:
        if f in texte:
            texte = texte.rsplit(f, 1)[1]
    for o in _OUVRANTES:
        if o in texte:
            texte = texte.split(o, 1)[0]
    return _JETON_SPECIAL.sub("", texte).strip()


def parser_termes(propre: str) -> List[str]:
    """Une réponse nettoyée -> la liste des termes à masquer, sans doublon, ordre conservé.
    Accepte : un terme par ligne (format demandé), puces et numéros, guillemets, une ligne en
    liste JSON (["a", "b"], le format des CANDIDATS que le modèle imite parfois), un préfixe
    « RÉPONSE : ». Jette : les en-têtes (ligne finissant par « : »), « (rien) », les phrases
    d'introduction. Le point final est retiré (un terme plus court masque plus, jamais moins)."""
    termes, vus = [], set()

    def ajoute(t):
        t = t.strip().strip("\"'`\u00ab\u00bb\u201c\u201d").strip().rstrip(" .,;").strip()
        if len(t) > 1 and t.lower() not in _RIEN and t not in vus:
            vus.add(t)
            termes.append(t)

    for ligne in propre.split("\n"):
        ligne = _PUCE.sub("", ligne.strip()).strip()
        ligne = _ENTETE.sub("", ligne).strip()
        if len(ligne) <= 1 or ligne.endswith(":"):
            continue
        bas = ligne.lower()
        # On évite de capturer des phrases d'intro du type "Voici la liste :"
        if "voici" in bas and ":" in ligne:
            continue
        if "liste" in bas and "masquer" in bas:
            continue
        if ligne.startswith("[") and ligne.endswith("]"):
            try:
                elements = json.loads(ligne)
            except ValueError:
                elements = re.split(r"\"\s*,\s*\"", ligne[1:-1])
            if isinstance(elements, list):
                for e in elements:
                    if isinstance(e, str):
                        ajoute(e)
                continue
        ajoute(ligne)
    return termes


class LlmAnalyzer:
    def __init__(self):
        self.config = ConfigLoader()
        self.model_name = self.config.get("llm.model_fallback", "gpt-oss:20b")

        # On augmente drastiquement le timeout car les modèles "Thinker" sont lents
        # 157s observées -> On met 600s (10min) pour être large sur les grosses pages
        self.timeout_val = int(self.config.get("llm.timeout_sec", 600))
        # Plafond de longueur PAR RÉPONSE (voir config.yaml) : une réponse est une liste de termes,
        # pas une rédaction. Sans plafond, une boucle de répétition tourne jusqu'au bout du contexte.
        self.num_predict = int(self.config.get("llm.num_predict", 1024))
        self.temperature = float(self.config.get("llm.temperature", 0.6))

        self.prompt_standard = self.config.get("llm.judge_prompt", "")
        self.prompt_extract = self.config.get("llm.extract_prompt", "")
        self.prompt_metiers = self.config.get("llm.metiers_prompt", "")

        try:
            self.client = Client(host='http://localhost:11434', timeout=self.timeout_val)
        except Exception as e:
            print(f"   [LLM Warning] Client init failed: {e}")

    def _appel(self, prompt: str, debug: bool = False) -> str:
        """Un appel au moteur, nettoyé de toute pensée. Si la réponse bute sur num_predict
        (done_reason == "length" : boucle de répétition, ou pensée qui ne finit pas), UN nouvel
        essai à température 0 ; s'il bute encore, LlmReponseTronqueeError — jamais une liste
        partielle rendue comme si elle était complète."""
        for temperature in (self.temperature, 0.0):
            response = self.client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'temperature': temperature,
                    'num_ctx': 16384,
                    'num_predict': self.num_predict,
                    'stop': []
                }
            )
            brut = response['message']['content'] or ""
            fin = response.get('done_reason') if hasattr(response, 'get') else None
            if debug:
                print(f"   [LLM] brut : {len(brut)} car., {response.get('eval_count')} jetons, fin={fin}")
            if fin != "length":
                return nettoyer_reponse(brut)
            print(f"   [LLM] Réponse tronquée à {self.num_predict} jetons (température {temperature}) : "
                  f"boucle ou pensée sans fin probable.")
        raise LlmReponseTronqueeError(
            f"réponse tronquée deux fois à {self.num_predict} jetons (température {self.temperature} puis 0) : "
            f"liste incomplète (boucle de répétition, ou « pensée » du modèle active : voir le journal du relais)")

    def get_final_redaction_list(self, page_text: str, initial_candidates: List[str], debug: bool = False) -> List[str]:
        if not page_text.strip():
            return []

        unique_candidates = sorted(list(set(initial_candidates)))
        count_candidates = len(unique_candidates)

        # Stratégie de bascule (densité)
        limit_high_density = 40
        # La bascule n'a de sens que si extract_prompt existe dans config.yaml : sinon l'invite
        # envoyée serait VIDE (c'est le cas aujourd'hui), sans aucune erreur.
        if count_candidates > limit_high_density and self.prompt_extract.strip():
            if debug: print(f"   [LLM] Mode EXTRACTION (Densité: {count_candidates})")
            prompt = self.prompt_extract.format(page_text=page_text)
        else:
            if debug: print(f"   [LLM] Mode VALIDATION (Densité: {count_candidates})")
            candidates_str = "\n".join([f"- {c}" for c in unique_candidates])
            prompt = self.prompt_standard.format(page_text=page_text, candidates_str=candidates_str)

        if debug:
            print(f"   [LLM] Envoi requête (Timeout={self.timeout_val}s)...")

        try:
            clean_content = self._appel(prompt, debug=debug)

            if debug:
                print("\n" + "=" * 20 + " RÉPONSE LLM (sans pensée) " + "=" * 20)
                print(clean_content)
                print("=" * 60 + "\n")

            final_terms = parser_termes(clean_content)

            print(f"   [LLM] -> {len(final_terms)} termes identifiés.")
            return final_terms

        except LlmIndisponibleError:
            raise  # réponse tronquée : le message dit déjà tout
        except Exception as e:
            print(f"   [LLM Error] {e}")
            if "Read timed out" in str(e):
                print("   [Conseil] Augmentez 'timeout_sec' dans config.yaml ou utilisez un modèle plus rapide.")
            # On ne rend SURTOUT PAS initial_candidates : sans le LLM, aucun nom n'est masqué.
            # L'erreur remonte, le pipeline marque le fichier FAILED et n'écrit pas de PDF.
            raise LlmIndisponibleError(f"Moteur LLM indisponible ({self.model_name}) : {e}") from e

    def get_metier_generalizations(self, page_text: str, debug: bool = False) -> List[tuple]:
        """Option --metiers (mode texte) : un second appel, qui ne masque pas mais GÉNÉRALISE
        les métiers rares ou identifiants. Rend une liste de (terme exact, généralisation).
        Une panne ici n'est PAS une LlmIndisponibleError : c'est une option, pas le cœur du
        masquage ; on la journalise et on rend une liste vide (rien de généralisé, rien de perdu
        côté confidentialité)."""
        if not page_text.strip() or not self.prompt_metiers.strip():
            return []

        prompt = self.prompt_metiers.format(page_text=page_text)

        try:
            clean_content = self._appel(prompt, debug=debug)

            if debug:
                print("\n" + "=" * 20 + " RÉPONSE LLM MÉTIERS " + "=" * 20)
                print(clean_content)
                print("=" * 60 + "\n")

            pairs = []
            for line in clean_content.split('\n'):
                clean_line = line.strip().lstrip("-").lstrip("*").strip()
                if "=>" not in clean_line:
                    continue
                terme, _, generalisation = clean_line.partition("=>")
                terme, generalisation = terme.strip(), generalisation.strip()
                if terme and generalisation:
                    pairs.append((terme, generalisation))

            print(f"   [LLM] -> {len(pairs)} métier(s) à généraliser.")
            return pairs

        except Exception as e:
            print(f"   [LLM Warning] Généralisation des métiers indisponible : {e}")
            return []
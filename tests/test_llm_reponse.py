"""Réponse du LLM : nettoyage de la pensée, lecture de la liste, réponse tronquée.
Sans moteur : un faux client. Contexte : le 05/10/2026, une pensée Gemma 4 coupée par la limite
a rendu un contenu vide -> 0 terme -> document SUCCESS avec le nom en clair."""
import unittest

from app.analyzers.LlmAnalyzer import (LlmAnalyzer, LlmIndisponibleError, LlmReponseTronqueeError,
                                       nettoyer_reponse, parser_termes)


class TestNettoyage(unittest.TestCase):
    def test_bloc_think_ferme(self):
        self.assertEqual(nettoyer_reponse("<think>je réfléchis</think>\nDupont"), "Dupont")

    def test_canal_gemma4_ferme(self):
        brut = "<|channel>thought\nAnalyse… Témoin Canari est un nom.\n<channel|>Témoin Canari\n14/03/2026"
        self.assertEqual(nettoyer_reponse(brut), "Témoin Canari\n14/03/2026")

    def test_pensee_tronquee_ne_donne_aucun_terme(self):
        # Pensée ouverte jamais fermée (coupée par num_predict) : rien de la pensée ne devient un terme.
        brut = "<|channel>thought\n* Line 1: \"14/03/2026\": Precise date. **MASK.**\n- Témoin Canari (Correct"
        self.assertEqual(nettoyer_reponse(brut), "")

    def test_pensee_ouverte_par_le_gabarit(self):
        # Le gabarit a déjà ouvert le canal : le contenu commence par la pensée et sa fermante.
        self.assertEqual(nettoyer_reponse("raisonnement…<channel|>Quarnec"), "Quarnec")

    def test_jetons_speciaux_retires(self):
        self.assertEqual(nettoyer_reponse("Quarnec<turn|>"), "Quarnec")


class TestParseur(unittest.TestCase):
    def test_un_terme_par_ligne(self):
        self.assertEqual(parser_termes("Témoin Canari\n02/11/1971\nBrévilly-sur-Ourche"),
                         ["Témoin Canari", "02/11/1971", "Brévilly-sur-Ourche"])

    def test_puces_numeros_guillemets(self):
        self.assertEqual(parser_termes('- Dupont\n* "Jean"\n1. Hôpital Nord\n2) Colmar'),
                         ["Dupont", "Jean", "Hôpital Nord", "Colmar"])

    def test_numero_de_telephone_et_date_pointee_intacts(self):
        # « 09. » n'est pas une numérotation : le téléphone ne doit pas perdre son premier groupe.
        self.assertEqual(parser_termes("09.72.13.01.07\n28.07.1965"), ["09.72.13.01.07", "28.07.1965"])

    def test_liste_json_imitee_des_candidats(self):
        self.assertEqual(parser_termes('["Dr Ysolde Quarnec", "Quarnec"]'), ["Dr Ysolde Quarnec", "Quarnec"])

    def test_entetes_et_rien_jetes(self):
        self.assertEqual(parser_termes("TA LISTE FINALE (Un terme par ligne) :\nVoici la liste :\n(rien)"), [])
        self.assertEqual(parser_termes("RÉPONSE : Quarnec"), ["Quarnec"])

    def test_boucle_de_repetition_dedoublonnee(self):
        self.assertEqual(parser_termes("Canari\nQuarnec\n" * 50), ["Canari", "Quarnec"])

    def test_point_final_retire(self):
        self.assertEqual(parser_termes("09 72 13 01 07."), ["09 72 13 01 07"])


class FauxClient:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    def chat(self, model, messages, options):
        self.appels.append(dict(options))
        contenu, fin = self.reponses.pop(0)
        return {"message": {"content": contenu}, "done_reason": fin, "eval_count": 1}


def analyseur(reponses):
    a = LlmAnalyzer.__new__(LlmAnalyzer)
    a.model_name, a.timeout_val, a.num_predict, a.temperature = "essai", 10, 1024, 0.6
    a.prompt_standard = "TEXTE {page_text} CANDIDATS {candidates_str}"
    a.prompt_extract = a.prompt_metiers = ""
    a.client = FauxClient(reponses)
    return a


class TestAppel(unittest.TestCase):
    def test_plafond_transmis(self):
        a = analyseur([("Quarnec", "stop")])
        self.assertEqual(a.get_final_redaction_list("Dr Quarnec", []), ["Quarnec"])
        self.assertEqual(a.client.appels[0]["num_predict"], 1024)
        self.assertEqual(a.client.appels[0]["temperature"], 0.6)

    def test_tronquee_puis_reussie_a_temperature_zero(self):
        a = analyseur([("<|channel>thought\nje pense", "length"), ("Quarnec", "stop")])
        self.assertEqual(a.get_final_redaction_list("Dr Quarnec", []), ["Quarnec"])
        self.assertEqual([o["temperature"] for o in a.client.appels], [0.6, 0.0])

    def test_tronquee_deux_fois_echec_franc(self):
        a = analyseur([("Canari\n" * 500, "length"), ("Canari\n" * 500, "length")])
        with self.assertRaises(LlmReponseTronqueeError):
            a.get_final_redaction_list("Témoin Canari", [])
        # Et c'est bien une panne du moteur pour le pipeline : FAILED, aucune sortie écrite.
        self.assertTrue(issubclass(LlmReponseTronqueeError, LlmIndisponibleError))

    def test_metiers_tronques_rendent_vide_sans_planter(self):
        a = analyseur([("x", "length"), ("x", "length")])
        a.prompt_metiers = "TEXTE {page_text}"
        self.assertEqual(a.get_metier_generalizations("facteur d'orgues"), [])


if __name__ == "__main__":
    unittest.main()

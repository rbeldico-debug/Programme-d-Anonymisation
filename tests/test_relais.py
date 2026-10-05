"""Relais Ollama -> llama-server : ce qu'il transmet (plafond, pensée) et ce qu'il rend (done_reason)."""
import importlib.util
import os
import unittest

_CHEMIN = os.path.join(os.path.dirname(__file__), "..", "outils", "relais_ollama.py")
_spec = importlib.util.spec_from_file_location("relais_ollama", _CHEMIN)
relais = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relais)

REQ = {"model": "m", "messages": [{"role": "user", "content": "x"}]}


class TestChargeAmont(unittest.TestCase):
    def test_num_predict_devient_max_tokens(self):
        c = relais.charge_amont({**REQ, "options": {"num_predict": 1024, "temperature": 0.6}})
        self.assertEqual(c["max_tokens"], 1024)
        self.assertEqual(c["temperature"], 0.6)

    def test_infini_ou_absent_borne_au_plafond(self):
        self.assertEqual(relais.charge_amont({**REQ, "options": {"num_predict": -1}})["max_tokens"],
                         relais.PLAFOND_JETONS)
        self.assertEqual(relais.charge_amont(REQ)["max_tokens"], relais.PLAFOND_JETONS)
        self.assertEqual(relais.charge_amont({**REQ, "options": {"num_predict": 10 ** 6}})["max_tokens"],
                         relais.PLAFOND_JETONS)

    def test_pensee_coupee_par_defaut(self):
        self.assertIs(relais.charge_amont(REQ)["chat_template_kwargs"]["enable_thinking"], False)
        self.assertIs(relais.charge_amont(REQ, pensee=True)["chat_template_kwargs"]["enable_thinking"], True)

    def test_temperature_forcee(self):
        self.assertEqual(relais.charge_amont({**REQ, "options": {"temperature": 0.6}}, 0.0)["temperature"], 0.0)


class TestReponse(unittest.TestCase):
    def _d(self, contenu, fin, raisonnement=""):
        return {"choices": [{"message": {"content": contenu, "reasoning_content": raisonnement},
                             "finish_reason": fin}], "usage": {"prompt_tokens": 700, "completion_tokens": 4096}}

    def test_troncature_dite(self):
        corps, trace = relais.reponse_ollama(self._d("", "length", "je pense…"), REQ)
        self.assertEqual(corps["done_reason"], "length")
        self.assertTrue(trace["vide"])
        self.assertTrue(trace["raisonnement"])

    def test_fin_normale(self):
        corps, trace = relais.reponse_ollama(self._d("Quarnec", "stop"), REQ)
        self.assertEqual(corps["done_reason"], "stop")
        self.assertEqual(corps["message"]["content"], "Quarnec")
        self.assertFalse(trace["vide"])


if __name__ == "__main__":
    unittest.main()

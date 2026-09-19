"""Tests des listes noire/blanche. Lancer depuis la racine : python -m unittest discover tests"""
import os
import shutil
import tempfile
import unittest

from app.core.filter_engine import FilterEngine


class TestFilterEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_lists(self, whitelist_lines=(), blacklist_lines=()):
        with open(os.path.join(self.tmp, "whitelist.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(whitelist_lines))
        with open(os.path.join(self.tmp, "blacklist.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(blacklist_lines))

    def test_dict_dir_par_parametre(self):
        self._write_lists(whitelist_lines=["Clinique Pasteur"], blacklist_lines=["Jean Fictif"])
        fe = FilterEngine(dict_dir=self.tmp)
        self.assertIn("clinique pasteur", fe.whitelist)
        self.assertIn("jean fictif", fe.blacklist)

    def test_dict_dir_par_variable_environnement(self):
        self._write_lists(whitelist_lines=["Terme Fictif"])
        os.environ["ANONYMIZER_DICT_DIR"] = self.tmp
        try:
            fe = FilterEngine()
            self.assertIn("terme fictif", fe.whitelist)
        finally:
            del os.environ["ANONYMIZER_DICT_DIR"]

    def test_absence_variable_comportement_inchange(self):
        # Sans ANONYMIZER_DICT_DIR ni dict_dir explicite : le défaut historique.
        self.assertNotIn("ANONYMIZER_DICT_DIR", os.environ)
        fe = FilterEngine()
        self.assertTrue(fe.whitelist == set() or isinstance(fe.whitelist, set))

    def test_listes_vides_par_defaut(self):
        self._write_lists()
        fe = FilterEngine(dict_dir=self.tmp)
        self.assertEqual(fe.whitelist, set())
        self.assertEqual(fe.blacklist, set())


if __name__ == "__main__":
    unittest.main()

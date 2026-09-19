"""Tests du décalage de dates. Lancer depuis la racine : python -m unittest discover tests"""
import unittest
from datetime import date

from app.core.date_shifter import shift_days_from_key, shift_date_text


class TestShiftDaysFromKey(unittest.TestCase):
    def test_meme_cle_meme_decalage(self):
        self.assertEqual(shift_days_from_key("patient-fictif-1"), shift_days_from_key("patient-fictif-1"))

    def test_bornes_et_jamais_zero(self):
        signes = set()
        for i in range(500):
            d = shift_days_from_key(f"cle-{i}")
            self.assertTrue(30 <= abs(d) <= 180, d)
            signes.add(d > 0)
        self.assertEqual(signes, {True, False})  # les deux sens existent

    def test_cles_differentes(self):
        valeurs = {shift_days_from_key(f"cle-{i}") for i in range(50)}
        self.assertGreater(len(valeurs), 20)

    def test_cle_vide_refusee(self):
        with self.assertRaises(ValueError):
            shift_days_from_key("")


class TestShiftDateText(unittest.TestCase):
    def test_formats_numeriques_conserves(self):
        self.assertEqual(shift_date_text("28/07/1965", 10), "07/08/1965")
        self.assertEqual(shift_date_text("28-07-1965", 10), "07-08-1965")
        self.assertEqual(shift_date_text("04.07.1982", -5), "29.06.1982")
        self.assertEqual(shift_date_text("05/02/25", 30), "07/03/25")
        self.assertEqual(shift_date_text("7/7/25", 1), "8/7/25")

    def test_annee_sur_deux_chiffres_ancienne(self):
        self.assertEqual(shift_date_text("12/03/65", 1), "13/03/65")

    def test_passage_d_annee(self):
        self.assertEqual(shift_date_text("20/12/2024", 40), "29/01/2025")

    def test_dates_en_lettres(self):
        self.assertEqual(shift_date_text("12 mars 2024", 30), "11 avril 2024")
        self.assertEqual(shift_date_text("21 Mai 2025", 11), "1er Juin 2025")
        self.assertEqual(shift_date_text("1er avril 2024", -1), "31 mars 2024")
        self.assertEqual(shift_date_text("3 fevrier 2024", 1), "4 février 2024")

    def test_intervalle_preserve(self):
        d = shift_days_from_key("patient-fictif-2")
        a = shift_date_text("02/09/2025", d)
        b = shift_date_text("15/09/2025", d)

        def lire(s):
            j, m, an = s.split("/")
            return date(int(an), int(m), int(j))

        self.assertEqual((lire(b) - lire(a)).days, 13)

    def test_non_decalable_rend_none(self):
        for texte in ["13/05", "31/02/2024", "mars 2024", "2017", "1er avril", "Dupont"]:
            self.assertIsNone(shift_date_text(texte, 45), texte)


if __name__ == "__main__":
    unittest.main()

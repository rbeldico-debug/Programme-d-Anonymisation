"""Variantes des noms rendus par le LLM (app/core/noms_composes.py). Sans moteur.
Contexte : le 05/10/2026, le LLM n'a rendu que « Clémence Ardouin-Vasseur » ; la chaîne exacte n'a pas
trouvé « Dr Ardouin-Vasseur. » plus bas, resté en clair. Noms inventés."""
import unittest

from app.core import noms_composes as nc

TEXTE = ("Médecin : Dr Clémence Ardouin-Vasseur.\nSuivi au CMP auprès du Dr Ardouin-Vasseur. "
         "Le Dr Ardouin relaie. Signé : C. ARDOUIN-VASSEUR. Érythème rose ; Mme Rose Lebrun.")


def masque(texte, termes, niveau, liste_noire=frozenset()):
    p = nc.motif_unique(termes, set(liste_noire), niveau)
    return p.sub("#", texte) if p else texte


class TestFormeNue(unittest.TestCase):
    def test_civilite_et_point_final(self):
        self.assertEqual(nc.forme_nue("Dr Ardouin-Vasseur."), "Ardouin-Vasseur")
        self.assertEqual(nc.forme_nue("Mme Rose Lebrun"), "Rose Lebrun")
        self.assertEqual(nc.forme_nue("M. le Pr Delorme"), "le Pr Delorme")  # seule la tête est retirée
        self.assertEqual(nc.forme_nue("« Pr Marc-Antoine Delorme »"), "Marc-Antoine Delorme")

    def test_sans_civilite_inchange(self):
        self.assertEqual(nc.forme_nue("Hôpital Nord"), "Hôpital Nord")
        self.assertEqual(nc.forme_nue("09.72.13.01.07"), "09.72.13.01.07")


class TestFormeDeNom(unittest.TestCase):
    def test_noms(self):
        for t in ("Clémence Ardouin-Vasseur", "Dr Hugues de La Roche-Vernay", "Pieter Van den Broeck",
                  "ARDOUIN-VASSEUR", "Anne Le Gall"):
            self.assertTrue(nc.a_forme_de_nom(t), t)

    def test_pas_des_noms(self):
        for t in ("Hôpital Nord", "10 rue de la Paix", "Morvillars-le-Haut", "14/03/2026",
                  "o.paskevitch@exemple-fictif.fr", "CHU de Vireloup", "trouble anxieux", "EHPAD Les Roches-Grises"):
            self.assertFalse(nc.a_forme_de_nom(t), t)


class TestNiveaux(unittest.TestCase):
    def test_aucun_est_le_comportement_d_avant(self):
        # Chaîne exacte, insensible à la casse, SANS frontière de mot (comme avant).
        self.assertEqual(masque("Clémence Ardouin-Vasseur et Dr Ardouin-Vasseur", ["Clémence Ardouin-Vasseur"], "aucun"),
                         "# et Dr Ardouin-Vasseur")
        self.assertEqual(masque("Dupontel", ["Dupont"], "aucun"), "#el")
        self.assertEqual(nc.deriver(["Dr Clémence Ardouin-Vasseur"], "aucun"), set())

    def test_titres_retire_civilite_seulement(self):
        self.assertEqual(nc.deriver(["Dr Ardouin-Vasseur.", "Clémence Ardouin-Vasseur"], "titres"),
                         {"Ardouin-Vasseur"})

    def test_le_cas_du_05_10_parties(self):
        sortie = masque(TEXTE, ["Clémence Ardouin-Vasseur"], "parties")
        self.assertNotIn("Ardouin-Vasseur", sortie)
        self.assertNotIn("ARDOUIN-VASSEUR", sortie)
        self.assertIn("Dr Ardouin relaie", sortie)        # un morceau seul : niveau « traits » seulement

    def test_traits_attrape_le_morceau_seul(self):
        sortie = masque(TEXTE, ["Clémence Ardouin-Vasseur"], "traits")
        self.assertIn("Dr # relaie", sortie)
        self.assertNotIn("Ardouin", sortie)

    def test_forme_entiere_toujours_cherchee(self):
        self.assertIn("Ardouin-Vasseur", nc.deriver(["Clémence Ardouin-Vasseur"], "traits"))

    def test_garde_majuscule(self):
        # « Rose » (prénom) ne masque pas « rose » (couleur) ; « ROSE » en capitales, si.
        sortie = masque(TEXTE + " ROSE LEBRUN", ["Mme Rose Lebrun"], "parties")
        self.assertIn("Érythème rose", sortie)
        self.assertTrue(sortie.endswith("; #. #"), sortie)  # « ROSE LEBRUN » = la forme nue, d'un bloc

    def test_civilites_morceau_seulement_apres_civilite(self):
        termes = ["Clémence Ardouin-Vasseur", "Noé Grand-Vallat"]
        sortie = masque("Le Dr Ardouin relaie. Dr. Vasseur. Mme Grand. Région Grand Est. Grand fumeur. Ardouin seul.",
                        termes, "civilites")
        self.assertEqual(sortie, "Le Dr # relaie. Dr. #. Mme #. Région Grand Est. Grand fumeur. Ardouin seul.")

    def test_civilites_attrape_le_cas_du_05_10(self):
        sortie = masque(TEXTE, ["Clémence Ardouin-Vasseur"], "civilites")
        self.assertNotIn("Ardouin", sortie)
        self.assertNotIn("ARDOUIN", sortie)

    def test_traits_morceaux_partout(self):
        self.assertEqual(masque("Grand Est", ["Noé Grand-Vallat"], "traits"), "# Est")

    def test_sous_composes_contigus(self):
        d = nc.morceaux(["Avril Saint-Martin-Lacoste"])
        self.assertEqual(d, {"Saint-Martin", "Martin-Lacoste", "Martin", "Lacoste"})  # jamais « Saint » seul
        self.assertEqual(masque("Mme Saint-Martin a refusé.", ["Avril Saint-Martin-Lacoste"], "civilites"),
                         "Mme # a refusé.")

    def test_mot_entier(self):
        self.assertEqual(masque("Pr Marc-Antoine Delorme, au marché ; Marcel", ["Pr Marc-Antoine Delorme"], "traits"),
                         "#, au marché ; Marcel")

    def test_particules_et_mots_courts_jamais_seuls(self):
        d = nc.deriver(["Hugues de La Roche-Vernay", "Pieter Van den Broeck", "Anne Le Gall", "Lou Bo"], "traits")
        for interdit in ("de", "La", "Van", "den", "Le", "Bo"):
            self.assertNotIn(interdit, d)
        self.assertTrue({"Roche-Vernay", "Roche", "Vernay", "Broeck", "Gall", "Hugues"} <= d)

    def test_lieux_jamais_decoupes(self):
        d = nc.deriver(["Hôpital Nord", "CHU de Vireloup", "Morvillars-le-Haut", "10 rue de la Paix"], "traits")
        for interdit in ("Nord", "Hôpital", "Vireloup", "Morvillars", "Haut", "Paix"):
            self.assertNotIn(interdit, d)

    def test_toponyme_a_trait_d_union_non_decoupe(self):
        self.assertFalse({"Saint", "Prix", "Vauge"} & nc.deriver(["Saint-Prix-sous-Vauge"], "traits"))

    def test_date_derivee_sans_garde_majuscule(self):
        # Une forme dérivée qui commence par un chiffre doit rester trouvable.
        self.assertEqual(masque("né le 08/04/1957.", ["08/04/1957."], "titres"), "né le #")

    def test_liste_noire_garde_sa_frontiere(self):
        self.assertEqual(masque("Paul et Paulette", ["paul"], "traits", {"paul"}), "# et Paulette")

    def test_niveau_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            nc.deriver(["x"], "tout")

    def test_motifs_du_plus_long_au_plus_court(self):
        longueurs = [len(t) for t, _ in nc.motifs(["Clémence Ardouin-Vasseur"], set(), "traits")]
        self.assertEqual(longueurs, sorted(longueurs, reverse=True))


if __name__ == "__main__":
    unittest.main()

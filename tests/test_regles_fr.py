"""Règles françaises d'avant le LLM (app/analyzers/regles_fr.py). Sans moteur, sans spaCy, sans réseau.
Contexte : banc PDF synthétique du 07/10/2026, couche Presidio seule — NIR 23/24 fuites, RPPS 29/32,
dates en lettres 28/32, « [MASQUÉ]ève-Haute », 102/116 éponymes pris pour des noms, et un
reconnaisseur de courriel qui télécharge la liste publicsuffix si son cache est vide.
Tous les numéros et noms sont inventés."""
import os
import socket
import tempfile
import unittest
from unittest import mock

from app.analyzers import regles_fr as rf


def trouve(reco, texte):
    return [(texte[r.start:r.end], r.score) for r in reco.analyze(texte, [reco.ENTITE])]


def textes(reco, texte):
    return [t for t, _ in trouve(reco, texte)]


def nir_valide(treize):
    return treize + "%02d" % rf.cle_nir(treize)


class TestNIR(unittest.TestCase):
    R = rf.RecoNIR()

    def test_cle_juste_sans_contexte(self):
        n = nir_valide("1850578006084")
        self.assertEqual(trouve(self.R, f"le {n} reste"), [(n, 1.0)])
        espace = f"{n[0]} {n[1:3]} {n[3:5]} {n[5:7]} {n[7:10]} {n[10:13]} {n[13:]}"
        self.assertEqual(trouve(self.R, f"x {espace}."), [(espace, 1.0)])
        points = espace.replace(" ", ".")
        self.assertEqual(textes(self.R, f"x {points} y"), [points])

    def test_cle_fausse_masquee_quand_meme(self):
        # une clé fausse est d'abord une faute de frappe ou d'OCR : 13 chiffres justes identifient
        self.assertEqual(trouve(self.R, "NIR : 2 70 03 88 198 544 57 — IPP"), [("2 70 03 88 198 544 57", 0.85)])
        self.assertEqual(trouve(self.R, "vu le 2 70 03 88 198 544 57."), [("2 70 03 88 198 544 57", 0.6)])

    def test_coupe_en_fin_de_ligne(self):
        t = "assuré ouvrant droit est le 2 75 10 88\n406 692 97. L'intéressé"
        self.assertEqual(textes(self.R, t), ["2 75 10 88\n406 692 97"])
        t = "NIR : 1 85 05 78  \n006 084 36"   # retour à la ligne Markdown (deux espaces)
        self.assertEqual(textes(self.R, t), ["1 85 05 78  \n006 084 36"])

    def test_sans_cle_exige_le_contexte(self):
        self.assertEqual(textes(self.R, "n° SS 1850578006084"), ["1850578006084"])
        self.assertEqual(textes(self.R, "numéro de sécurité sociale : 1 85 05 78 006 084"), ["1 85 05 78 006 084"])
        self.assertEqual(textes(self.R, "numero de secu 1820754189456 clé 42"), ["1820754189456 clé 42"])
        self.assertEqual(textes(self.R, "lot 1850578006084"), [])
        # contre-épreuve du 07/10 : « assurée » n'était pas un contexte (passé par chance, la ligne
        # du dessus disait « sécurité sociale »)
        self.assertEqual(textes(self.R, "Numéro d'assurée : 1770257463125"), ["1770257463125"])

    def test_cip13_n_est_pas_un_nir(self):
        # même structure qu'un NIR sans clé (sexe 3, mois 09) : rejeté faute de contexte
        self.assertEqual(textes(self.R, "Sertraline 50 mg, CIP 3400936403114"), [])

    def test_corse(self):
        n = nir_valide("185052A006084")
        self.assertEqual(trouve(self.R, f"NIR {n}"), [(n, 1.0)])
        self.assertEqual(rf.cle_nir("1850519006084"), rf.cle_nir("185052A006084"))

    def test_ni_telephone_ni_date(self):
        for t in ("tél. 06 39 98 48 58", "03.83.15.22.01", "né le 12/03/1978", "IPP 5401224",
                  "Dossier 2025-59230", "12 345 678 901 234 567 890"):
            self.assertEqual(textes(self.R, t), [], t)


class TestRPPS(unittest.TestCase):
    R = rf.RecoRPPS()

    def test_forme_10_sans_contexte(self):
        self.assertEqual(trouve(self.R, "Dr Untel, 10101234567."), [("10101234567", 0.6)])
        self.assertEqual(textes(self.R, "e-CPS 810101234567"), ["810101234567"])

    def test_contexte_rpps_ou_adeli(self):
        self.assertEqual(trouve(self.R, "RPPS 99000261629 — c.x@example.org"), [("99000261629", 1.0)])
        self.assertEqual(textes(self.R, "n° RPPS : 10 1234 5678 9"), ["10 1234 5678 9"])
        self.assertEqual(textes(self.R, "ADELI 541234567"), ["541234567"])

    def test_pas_un_rpps(self):
        self.assertEqual(textes(self.R, "n° 99000261629"), [])        # 11 chiffres sans contexte, pas en 10
        self.assertEqual(textes(self.R, "tél 0612345678"), [])
        # le téléphone qui SUIT un RPPS n'est pas un RPPS
        self.assertEqual(textes(self.R, "RPPS 99000261629 — Tél. 03 53 01 80 89"), ["99000261629"])


class TestDateLettres(unittest.TestCase):
    R = rf.RecoDateLettres()

    def test_toutes_lettres(self):
        cas = {
            "Sortie le trente juillet deux mille vingt-cinq, au domicile": "trente juillet deux mille vingt-cinq",
            "le vingt et un mai 2024 et": "vingt et un mai 2024",
            "Fait le premier août mil neuf cent quatre-vingt-dix-huit.": "premier août mil neuf cent quatre-vingt-dix-huit",
            "Douze mars, il revient": "Douze mars",
            "le neuf juin deux mille vingt-cinq et sera vu": "neuf juin deux mille vingt-cinq",
        }
        for t, attendu in cas.items():
            self.assertEqual(textes(self.R, t), [attendu], t)

    def test_chiffres_et_abreviations(self):
        self.assertEqual(textes(self.R, "le 3 avril"), ["3 avril"])
        self.assertEqual(textes(self.R, "le 1er avril"), ["1er avril"])
        self.assertEqual(textes(self.R, "12 janv. 2024"), ["12 janv. 2024"])
        self.assertEqual(textes(self.R, "le 3 sept 2024"), ["3 sept 2024"])

    def test_durees_et_mois_seuls_non(self):
        for t in ("depuis trois mois", "sept mois plus tard", "deux ans", "en mars 2024",
                  "mars deux mille vingt-quatre", "à six mois sous traitement", "un mardi"):
            self.assertEqual(textes(self.R, t), [], t)


class TestVoie(unittest.TestCase):
    R = rf.RecoVoie()

    def test_unicode_et_apostrophe_courbe(self):
        self.assertEqual(textes(self.R, "Adresse : 36 chemin de la Grève-Haute, 54700"), ["36 chemin de la Grève-Haute"])
        self.assertEqual(textes(self.R, "62 rue de l’Abbé-Fringant, 54200 Toul"), ["62 rue de l’Abbé-Fringant"])
        self.assertEqual(textes(self.R, "avenue du Général de Gaulle."), ["avenue du Général de Gaulle"])
        self.assertEqual(textes(self.R, "place du 8 Mai 1945"), ["place du 8 Mai 1945"])

    def test_jamais_a_travers_une_ligne(self):
        self.assertEqual(textes(self.R, "39 chemin de la Grève-Haute  \n54000 Nancy"), ["39 chemin de la Grève-Haute"])
        self.assertEqual(textes(self.R, "14 rue des quatre eglises 54000 nancy"), ["14 rue des quatre eglises"])

    def test_mots_courants_sans_majuscule(self):
        for t in ("mise en place d'un traitement", "au cours de la journée", "à mi-chemin du parcours",
                  "en route vers Metz", "la place du patient", "le chemin parcouru"):
            self.assertEqual(textes(self.R, t), [], t)

    def test_queue_en_minuscules_retiree(self):
        self.assertEqual(textes(self.R, "habite rue Pasteur et il vient"), ["rue Pasteur"])


class TestCodePostalVille(unittest.TestCase):
    R = rf.RecoCodePostalVille()

    def test_communes(self):
        self.assertEqual(textes(self.R, "54700 Pont-à-Mousson  \n"), ["Pont-à-Mousson"])
        self.assertEqual(textes(self.R, "54500 Vandœuvre-lès-Nancy, le"), ["Vandœuvre-lès-Nancy"])
        self.assertEqual(textes(self.R, "76600 Le Havre"), ["Le Havre"])
        self.assertEqual(textes(self.R, "57000 Metz Cedex 1 — tél"), ["Metz Cedex 1"])

    def test_un_seul_mot_et_pas_de_mot_outil(self):
        # en mode PDF, les lignes sont jointes par une espace : « Objet » est la ligne suivante
        self.assertEqual(textes(self.R, "54700 Pont-à-Mousson Objet : M."), ["Pont-à-Mousson"])
        self.assertEqual(textes(self.R, "IPP 54012 Le patient"), [])
        self.assertEqual(textes(self.R, "54012 L’hôpital"), [])


class TestCourrielHorsLigne(unittest.TestCase):
    """tldextract télécharge publicsuffix.org si son cache est vide. Ici : aucun accès réseau, aucun
    fichier de cache, et le résultat est le même."""

    def test_aucun_reseau_aucun_cache(self):
        tentatives = []

        def interdit(*a, **k):
            tentatives.append(a)
            raise OSError("réseau interdit pendant le test")

        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache, "TLDEXTRACT_CACHE": cache}), \
                mock.patch.object(socket.socket, "connect", interdit), \
                mock.patch.object(socket, "getaddrinfo", interdit), \
                mock.patch.object(socket, "create_connection", interdit):
            # un extracteur NEUF, construit comme dans le module : il n'a encore rien chargé
            neuf = type(rf.EXTRACTEUR_HORS_LIGNE)(cache_dir=None, suffix_list_urls=(), fallback_to_snapshot=True)
            self.assertEqual(neuf("heloise.fontaine@courriel.example.org").fqdn, "courriel.example.org")
            reco = rf.EmailHorsLigne(supported_language="fr")
            res = reco.analyze("écrire à c.ardouin@hauteseille.example.org svp", ["EMAIL_ADDRESS"], None)
            self.assertEqual([r.entity_type for r in res], ["EMAIL_ADDRESS"])
            self.assertEqual(os.listdir(cache), [])
        self.assertEqual(tentatives, [])

    def test_le_global_de_tldextract_est_remplace(self):
        import tldextract
        import tldextract.tldextract as module
        self.assertIs(module.TLD_EXTRACTOR, rf.EXTRACTEUR_HORS_LIGNE)
        self.assertEqual(rf.EXTRACTEUR_HORS_LIGNE.suffix_list_urls, ())
        self.assertEqual(tldextract.extract("x@a.example.org").suffix, "org")


class TestEponymes(unittest.TestCase):
    def ecarte(self, texte, mot):
        i = texte.index(mot)
        return rf.eponyme_en_contexte(texte, i, i + len(mot))

    def test_ecartes_dans_leur_contexte(self):
        for t, m in [("échelle de Hamilton à 22", "Hamilton"), ("maladie de Parkinson", "Parkinson"),
                     ("inventaire de dépression de Beck", "Beck"), ("le MMSE de Folstein", "Folstein"),
                     ("maladie de Charcot-Marie-Tooth", "Charcot-Marie-Tooth"),
                     ("démence de type Alzheimer", "Alzheimer"), ("maladie à corps de Lewy", "Lewy"),
                     ("syndrome de Gilles de la Tourette", "Gilles de la Tourette"),
                     ("test des cinq mots de Dubois", "Dubois")]:
            self.assertTrue(self.ecarte(t, m), t)

    def test_un_patient_qui_porte_le_nom_reste_candidat(self):
        for t, m in [("M. Hamilton est venu", "Hamilton"), ("la maladie de Beck", "Beck"),
                     ("la maladie de Marie", "Marie"), ("la maladie de Mme Beck", "Beck"),
                     ("Hamilton. Échelle de", "Hamilton"), ("chez Dubois, test de", "Dubois"),
                     ("échelle de Dupont", "Dupont")]:
            self.assertFalse(self.ecarte(t, m), t)

    def test_meme_mot_ailleurs_hors_contexte_garde_le_candidat(self):
        # contre-épreuve du 07/10 : spaCy n'a vu la patiente que sous « Odile Beck » ; c'est le « Beck »
        # de l'inventaire qui masquait « Mme Beck décrit » — l'écarter l'a fait fuir deux fois
        t = "Mme Odile Beck, 52 ans. Inventaire de dépression de Beck à 31. Mme Beck décrit une tristesse."
        i = t.index("Beck à")
        self.assertFalse(rf.eponyme_en_contexte(t, i, i + 4))
        t = "Inventaire de dépression de Beck à 31, puis test de Beck à 12."
        i = t.index("Beck")
        self.assertTrue(rf.eponyme_en_contexte(t, i, i + 4))


class TestTelFranceConfig(unittest.TestCase):
    """La règle TelFrance de config.yaml ne mord plus dans un code CIP13."""

    def test_cip_et_telephones(self):
        import re
        import yaml
        regle = [r for r in yaml.safe_load(open("config.yaml"))["presidio"]["custom_rules"] if r["name"] == "TelFrance"][0]
        rx = re.compile(regle["regex"], re.DOTALL | re.MULTILINE | re.IGNORECASE)   # drapeaux de Presidio
        self.assertEqual(rx.findall("CIP 3400936403114"), [])
        for tel in ("03 29 08 41 76", "03.87.31.60.24", "0612345678", "+33 6 12 34 56 78"):
            self.assertEqual([m.group() for m in rx.finditer(f"tél. {tel}.")], [tel], tel)


class TestPipelineSansMoteur(unittest.TestCase):
    """FR_RPPS est masqué d'office ; un éponyme en contexte n'est plus donné au LLM, « M. Hamilton » si."""

    def setUp(self):
        from app.core.pipeline import AnonymizationPipeline
        pl = AnonymizationPipeline.__new__(AnonymizationPipeline)
        self.texte = "RPPS 10101234567. Échelle de Hamilton à 22. M. Hamilton est venu."
        a, b = self.texte.index("Hamilton"), self.texte.rindex("Hamilton")
        pl.local_analyzer = mock.Mock()
        pl.local_analyzer.analyze_text.return_value = [
            {"type": "FR_RPPS", "start": 5, "end": 16, "text_slice": "10101234567"},
            {"type": "PERSON", "start": a, "end": a + 8, "text_slice": "Hamilton"},
            {"type": "PERSON", "start": b, "end": b + 8, "text_slice": "Hamilton"},
        ]
        pl.llm_analyzer = mock.Mock()
        pl.llm_analyzer.get_final_redaction_list.side_effect = lambda page_text, initial_candidates, debug: initial_candidates
        pl.filter_engine = mock.Mock(whitelist=set(), blacklist=set(), **{"est_blanc.return_value": False})
        self.pl = pl

    def test_rpps_d_office_et_patient_garde(self):
        self.pl.eponymes_en_contexte = True
        secrets = self.pl._collect_page_secrets(self.texte)
        self.assertIn("10101234567", secrets)
        self.assertIn("Hamilton", secrets)   # « M. Hamilton » : candidat, donc masqué partout

    def test_eponyme_seul_ecarte(self):
        # sans « M. Hamilton » sur la page : l'éponyme n'est plus donné au LLM
        self.pl.eponymes_en_contexte = True
        self.pl.local_analyzer.analyze_text.return_value = self.pl.local_analyzer.analyze_text.return_value[:2]
        texte = self.texte.replace("M. Hamilton est venu.", "")
        self.assertEqual(self.pl._collect_page_secrets(texte), {"10101234567"})

    def test_reglage_eteint_comme_avant(self):
        self.pl.eponymes_en_contexte = False
        self.pl.local_analyzer.analyze_text.return_value = self.pl.local_analyzer.analyze_text.return_value[:2]
        self.assertEqual(self.pl._collect_page_secrets(self.texte), {"10101234567", "Hamilton"})


if __name__ == "__main__":
    unittest.main()

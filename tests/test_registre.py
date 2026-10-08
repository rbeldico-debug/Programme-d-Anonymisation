"""Registre des entrées masquées, liste noire en mot entier, liste blanche normalisée, audits.
Tout est fictif ; aucun moteur (ni Presidio ni LLM) n'est chargé."""
import collections
import contextlib
import csv
import importlib.util
import io
import os
import re
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from app.core import noms_composes, registre as R
from app.core.filter_engine import FilterEngine, motif_mot_entier, normaliser_terme


def _outil(nom):
    chemin = os.path.join(os.path.dirname(__file__), "..", "outils", nom + ".py")
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def trouve(terme, texte):
    return [m.group() for m in re.finditer(motif_mot_entier(terme), texte, re.IGNORECASE)]


class TestMotEntier(unittest.TestCase):
    def test_pas_dans_un_mot_plus_long(self):
        self.assertEqual(trouve("fort", "un effort, un fort, forté, FORT."), ["fort", "FORT"])
        self.assertEqual(trouve("Élodie", "Mélodie et Élodie"), ["Élodie"])

    def test_accent_combinant_est_une_lettre(self):
        self.assertEqual(trouve("cafe", "café noir"), [])

    def test_ponctuation_finale(self):
        # avec \b des deux côtés, « Dr Dupont. » n'était JAMAIS trouvé devant une espace ou en fin de texte
        self.assertEqual(trouve("Dr Dupont.", "Vu par le Dr Dupont. Puis Dr Dupont."), ["Dr Dupont.", "Dr Dupont."])

    def test_apostrophes_et_elision(self):
        self.assertEqual(trouve("d'Orléans", "né d’Orléans"), ["d’Orléans"])
        self.assertEqual(trouve("Orléans", "né d’Orléans, à Orléans"), ["Orléans", "Orléans"])

    def test_blancs_et_fin_de_ligne(self):
        self.assertEqual(trouve("Jean  Dupont", "Jean\nDupont"), ["Jean\nDupont"])

    def test_trait_d_union_borne(self):
        self.assertEqual(trouve("Vasseur", "Ardouin-Vasseur"), ["Vasseur"])

    def test_motifs_liste_noire_et_majuscule(self):
        rx = noms_composes.motif_unique({"fort", "Rose"}, {"fort"}, majuscule={"rose"})
        self.assertEqual(rx.sub("#", "effort Fort. érythème rose, Rose Ardouin"), "effort #. érythème rose, # Ardouin")

    def test_normaliser_terme(self):
        self.assertEqual(normaliser_terme(" « L’Haÿ-les-Roses. » "), "l'haÿ-les-roses")
        self.assertEqual(normaliser_terme("Sommeil"), "sommeil")
        self.assertNotEqual(normaliser_terme("Lefèvre"), normaliser_terme("lefevre"))  # accents gardés


class _Dico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def ecrire(self, nom, texte):
        with open(os.path.join(self.tmp, nom), "w", encoding="utf-8") as f:
            f.write(texte)


class TestFilterEngine(_Dico):
    def test_liste_blanche_normalisee(self):
        self.ecrire("whitelist.txt", "Sommeil.\nL’Abbé\n")
        fe = FilterEngine(dict_dir=self.tmp)
        self.assertTrue(fe.est_blanc("sommeil"))
        self.assertTrue(fe.est_blanc("SOMMEIL"))
        self.assertTrue(fe.est_blanc("l'abbé"))
        self.assertFalse(fe.est_blanc("l'abbe"))  # pas de repli des accents : la liste blanche démasque

    def test_registre_charge_et_liste_blanche_l_emporte(self):
        self.ecrire("whitelist.txt", "rose\nsommeil\n")
        self.ecrire(R.NOM_FICHIER, "# c\n2026-10-08\tPERSON\tRose Ardouin-Vasseur\tRose | Ardouin-Vasseur | Ardouin\n"
                                   "2026-10-08\tLLM\tsommeil\n"
                                   "ligne illisible\n")
        fe = FilterEngine(dict_dir=self.tmp)
        self.assertEqual(fe.registre_entrees, {"Rose Ardouin-Vasseur"})
        self.assertEqual(fe.registre_variantes, {"Ardouin-Vasseur", "Ardouin"})
        self.assertEqual(fe.registre_ecartes, 2)
        self.assertIn("rose ardouin-vasseur", fe.formes_bornees())
        self.assertEqual(fe.formes_majuscule(), {"ardouin-vasseur", "ardouin"})

    def test_liste_noire_en_mot_entier_apply_filters(self):
        self.ecrire("blacklist.txt", "fort\n")
        fe = FilterEngine(dict_dir=self.tmp)
        r = fe.apply_filters("un effort fort", [])
        self.assertEqual([(e["start"], e["end"]) for e in r], [(10, 14)])


class TestFichierRegistre(_Dico):
    def test_aller_retour_atomique(self):
        p = os.path.join(self.tmp, R.NOM_FICHIER)
        self.ecrire(R.NOM_FICHIER, "# mon commentaire\nligne illisible\n2026-10-01\tPERSON\tJean Fictif\tFictif\n")
        reg = R.lire(p)
        self.assertEqual(reg.illisibles, 1)
        reg.lignes.append(R.Entree("2026-10-08", "LOCATION", "Brévilly-sur-Ourche", []))
        R.ecrire(p, reg)
        with open(p, encoding="utf-8") as f:
            texte = f.read()
        self.assertIn("# mon commentaire\nligne illisible\n2026-10-01\tPERSON\tJean Fictif\tFictif\n", texte)
        self.assertTrue(texte.startswith("# REGISTRE"))
        self.assertTrue(texte.endswith("2026-10-08\tLOCATION\tBrévilly-sur-Ourche\n"))
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".tmp")], [])
        R.ecrire(p, R.lire(p))
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read().count("# REGISTRE"), 1)


def _audit(*lignes):
    return [dict(page="1", text=t, entity_type=ty, source=s, score="1.0") for t, ty, s in lignes]


COURANTS = {"sommeil", "fort", "heureusement", "rose", "petit", "le", "de"}


def recolte(reg, audits, blanche=(), noire=(), **k):
    return R.recolter(reg, audits, normaliser=normaliser_terme,
                      est_blanc=lambda t: normaliser_terme(t) in {normaliser_terme(b) for b in blanche},
                      liste_noire=set(noire), est_courant=lambda m: m.lower() in COURANTS,
                      deriver=R.variantes_de, date="2026-10-08", **k)


class TestRecolte(unittest.TestCase):
    def test_entree_et_variantes_sans_doublon(self):
        reg = R.Registre(lignes=[])
        a = _audit(("Dr Clémence Ardouin-Vasseur", "PERSON", "LLM"), ("Ardouin-Vasseur.", "LLM", "LLM"),
                   ("Clémence Ardouin-Vasseur", "PERSON", "LLM"), ("Mme Héloïse d’Estrébourg", "PERSON", "LLM"))
        b = recolte(reg, [a])
        self.assertEqual(b.nouvelles_entrees, 2)
        e = {x.entree: x for x in reg.entrees}
        self.assertEqual(set(e), {"Dr Clémence Ardouin-Vasseur", "Mme Héloïse d’Estrébourg"})
        self.assertEqual(set(e["Dr Clémence Ardouin-Vasseur"].variantes),
                         {"Clémence Ardouin-Vasseur", "Ardouin-Vasseur", "Clémence", "Ardouin", "Vasseur"})
        self.assertIn("Estrébourg", e["Mme Héloïse d’Estrébourg"].variantes)
        self.assertEqual(b.deja_au_registre, 2)  # les deux formes plus courtes sont déjà des variantes
        b2 = recolte(reg, [a])                     # seconde récolte : rien de neuf
        self.assertEqual((b2.nouvelles_entrees, len(reg.entrees)), (0, 2))

    def test_rien_n_est_retire(self):
        reg = R.Registre(lignes=[R.Entree("2026-10-01", "PERSON", "Jean Fictif", [])])
        recolte(reg, [_audit(("Brévilly-sur-Ourche", "LOCATION", "LLM"))])
        self.assertEqual([e.entree for e in reg.entrees], ["Jean Fictif", "Brévilly-sur-Ourche"])

    def test_gardes_et_suspects(self):
        reg = R.Registre(lignes=[])
        b = recolte(reg, [_audit(("Le", "PERSON", "LLM"), ("sommeil", "LLM", "LLM"), ("Sommeil", "LLM", "LLM"),
                                 ("Fort heureusement", "PERSON", "LLM"), ("hydroxyzine", "PERSON", "LLM"),
                                 ("12/03/1971", "DATE", "REGLE"), ("Jean Petit", "PERSON", "LLM"),
                                 ("Jean Fictif", "REGISTRE", "REGISTRE"))])
        self.assertEqual(b.trop_courts, 1)
        self.assertEqual(b.suspects_mot_courant, 2)    # sommeil (deux casses = une clé), Fort heureusement
        self.assertEqual(b.suspects_minuscules, 1)     # hydroxyzine, jamais écrit avec une majuscule
        self.assertEqual(b.types_regles, 1)
        self.assertEqual(b.deja_permanents, 1)
        e = reg.entrees
        self.assertEqual([x.entree for x in e], ["Jean Petit"])
        self.assertNotIn("Petit", e[0].variantes)      # mot courant : jamais seul
        self.assertIn("Jean", e[0].variantes)

    def test_liste_blanche_et_liste_noire(self):
        reg = R.Registre(lignes=[])
        b = recolte(reg, [_audit(("Brévilly", "LOCATION", "LLM"), ("Jean Fictif", "PERSON", "LLM"))],
                    blanche={"brévilly"}, noire={"jean fictif"})
        self.assertEqual((b.liste_blanche, b.liste_noire, b.nouvelles_entrees), (1, 1, 0))


class TestOutilRegistre(_Dico):
    def test_terminal_sans_terme_et_dictionnaires_exiges(self):
        outil = _outil("registre")
        sortie = os.path.join(self.tmp, "sortie")
        dico = os.path.join(self.tmp, "dico")
        os.makedirs(sortie)
        os.makedirs(dico)
        with open(os.path.join(sortie, "doc.md_audit.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["page", "text", "entity_type", "source", "score"])
            for t in ("Clotaire Hautefeuille-Brun", "sommeil", "Sommeil"):
                w.writerow([1, t, "LLM", "LLM", 1.0])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANONYMIZER_DICT_DIR", None)
            with self.assertRaises(SystemExit):
                outil.main(["recolter", sortie])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(outil.main(["recolter", sortie, "--dictionnaires", dico]), 0)
        texte = out.getvalue()
        for mot in ("Clotaire", "Hautefeuille", "sommeil", "Sommeil", "doc.md"):
            self.assertNotIn(mot, texte)
        self.assertIn("1 mots courants", texte)
        reg = R.lire(os.path.join(dico, R.NOM_FICHIER))
        self.assertEqual([e.entree for e in reg.entrees], ["Clotaire Hautefeuille-Brun"])


class TestMotsCourants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.mots_courants import MotsCourants
        cls.mc = MotsCourants()

    def test_courants(self):
        for m in ("sommeil", "Sommeil", "Fort", "rose", "Claire", "heureusement", "de"):
            self.assertTrue(self.mc.est_courant(m), m)

    def test_noms_sauves(self):
        for m in ("Martin", "Pierre", "Jean", "Dupont", "Leroy", "Ardouin-Vasseur", "Clémence"):
            self.assertFalse(self.mc.est_courant(m), m)


class TestPipelineRegistre(_Dico):
    """Mode texte, sans moteur : le registre masque, la liste blanche l'emporte, l'audit est rempli."""

    def _pipeline(self):
        from app.core.pipeline import AnonymizationPipeline
        pl = AnonymizationPipeline.__new__(AnonymizationPipeline)
        pl.local_analyzer = mock.Mock(**{"analyze_text.return_value": []})
        pl.llm_analyzer = mock.Mock(**{"get_final_redaction_list.return_value": [],
                                       "get_metier_generalizations.return_value": []})
        pl.filter_engine = FilterEngine(dict_dir=self.tmp)
        pl.niveau_noms = "aucun"
        pl.eponymes_en_contexte = False
        return pl

    def test_texte(self):
        self.ecrire(R.NOM_FICHIER, "2026-10-08\tPERSON\tRose Ardouin-Vasseur\tRose | Ardouin-Vasseur | Ardouin\n"
                                   "2026-10-08\tLLM\tPénombre\n")
        self.ecrire("whitelist.txt", "pénombre\n")
        entree = os.path.join(self.tmp, "e.md")
        sortie = os.path.join(self.tmp, "s.md")
        with open(entree, "w", encoding="utf-8") as f:
            f.write("ROSE ARDOUIN-VASSEUR vue. Dr Ardouin. Érythème rose. Rose dort. Pénombre. Ardouinière.\n")
        r = self._pipeline().process_text_file(entree, sortie)
        with open(sortie, encoding="utf-8") as f:
            self.assertEqual(f.read(), "[MASQUÉ] vue. Dr [MASQUÉ]. Érythème rose. [MASQUÉ] dort. Pénombre. Ardouinière.\n")
        self.assertEqual(r.status, "SUCCESS")
        self.assertEqual([(d.text, d.source) for d in r.details],
                         [("ROSE ARDOUIN-VASSEUR", "REGISTRE"), ("Ardouin", "REGISTRE"), ("Rose", "REGISTRE")])


class TestReconstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _outil("reconstruire_audits")

    def test_texte(self):
        t = self.m.termes_texte
        self.assertEqual(t("Jean Dupont est venu à Toul.", "[MASQUÉ] [MASQUÉ] est venu à [MASQUÉ]."),
                         ["Jean", "Dupont", "Toul"])
        self.assertEqual(t("Vu: Jean Dupont", "Vu: [MASQUÉ][MASQUÉ]"), ["Jean Dupont"])
        self.assertEqual(t("rien", "rien"), [])
        self.assertIsNone(t("Jean est là", "[MASQUÉ] était là"))

    def test_pdf(self):
        import fitz
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        e, s = os.path.join(tmp, "e.pdf"), os.path.join(tmp, "s.pdf")
        d = fitz.open()
        p = d.new_page()
        p.insert_text((50, 72), "Patient Clotaire Hautefeuille vu ce jour", fontsize=11)
        d.save(e)
        p = d[0]
        for r in p.search_for("Clotaire Hautefeuille"):
            p.add_redact_annot(r, fill=(0, 0, 0))
        p.apply_redactions()
        d.save(s)
        self.assertEqual(self.m.termes_pdf(e, s), [(1, "Clotaire Hautefeuille")])


class TestComparaison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _outil("comparer_sorties")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pdf, self.md = os.path.join(self.tmp, "cr-2026"), os.path.join(self.tmp, "obsidian")
        os.makedirs(self.pdf)
        os.makedirs(self.md)

    def audit(self, dossier, nom, *lignes):
        with open(os.path.join(dossier, nom), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["page", "text", "entity_type", "source", "score"])
            for t, ty in lignes:
                w.writerow([1, t, ty, "LLM", 1.0])

    def test_appariement_et_deux_niveaux(self):
        self.audit(self.pdf, "2026-03-12 CH.pdf_audit.csv", ("Dr Clotaire Hautefeuille", "PERSON"),
                   ("sommeil", "LLM"), ("Toul", "LOCATION"))
        self.audit(self.md, "2026-03-12 ch.md_audit.csv", ("Clotaire Hautefeuille", "PERSON"),
                   ("Dr", "PERSON"), ("Toul", "LOCATION"), ("Brévilly", "LOCATION"))
        self.audit(self.pdf, "2026-04-01 XY.pdf_audit.csv", ("Ysaline", "PERSON"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.m.main(["--pdf", self.pdf, "--md", self.md]), 0)
        texte = out.getvalue()
        self.assertIn("paires appariées : 1 ; PDF sans pendant : 1 ; .md sans pendant : 0", texte)
        # mots : {dr, clotaire, hautefeuille, sommeil, toul} contre {clotaire, hautefeuille, dr, toul, brévilly}
        self.assertIn("Jaccard : moyen 0,67", texte)
        self.assertIn("propres au PDF : 1 (dans 1 paires), dont 1 mots courants", texte)
        self.assertIn("types, propres au PDF : LLM 1", texte)
        for interdit in ("Clotaire", "Hautefeuille", "sommeil", "Toul", "Brévilly", "Ysaline", "2026-03-12", "CH"):
            self.assertNotIn(interdit, texte)
        with open(os.path.join(self.pdf, self.m.NOM_DETAIL), encoding="utf-8") as f:
            detail = f.read()
        self.assertIn("sommeil [LLM] (courant)", detail)
        self.assertIn("brévilly [LOCATION]", detail)
        self.assertIn("PDF seulement : 2026-04-01 XY.pdf_audit.csv", detail)

    def test_unite_termes(self):
        a = {"x": ("x.pdf_audit.csv", {"dr dupont": collections.Counter(PERSON=1)})}
        b = {"x": ("x.md_audit.csv", {"dupont": collections.Counter(PERSON=1)})}
        c, paires = self.m.comparer(a, b)
        self.assertEqual((c["j_min"], c["u_pdf"], c["u_md"]), (0.0, 1, 1))


if __name__ == "__main__":
    unittest.main()

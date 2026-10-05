"""Entrées du lot : .txt et .md en mode texte ; un PDF scanné (image sans texte) est SIGNALÉ, jamais
recopié comme anonymisé. Sans moteur : le scan est écarté avant tout appel aux analyseurs."""
import os
import shutil
import tempfile
import unittest

import fitz

from app.core.batch_processor import lister_entrees
from app.core.pdf_processor import PdfProcessor
from app.core.pipeline import AnonymizationPipeline


def pdf_texte(chemin, texte="Patient : Témoin Canari, né le 02/11/1971, vu à Brévilly-sur-Ourche."):
    d = fitz.open()
    d.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), texte, fontsize=11)
    d.save(chemin)


def pdf_scan(chemin, entete=None):
    """Une page rendue en IMAGE (pixels seulement), comme un scan ; option : un en-tête texte de fax."""
    source = fitz.open()
    source.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), "Patient : Témoin Canari", fontsize=14)
    pix = source[0].get_pixmap(dpi=60)
    d = fitz.open()
    p = d.new_page()
    p.insert_image(p.rect, pixmap=pix)
    if entete:
        p.insert_text((20, 15), entete, fontsize=7)
    d.save(chemin)


class TestEntrees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _touch(self, nom):
        open(os.path.join(self.tmp, nom), "w").close()

    def test_mode_texte_prend_txt_et_md(self):
        for nom in ("b.md", "a.txt", "c.MD", "d.pdf", "e.docx"):
            self._touch(nom)
        os.mkdir(os.path.join(self.tmp, "dossier.md"))
        self.assertEqual(lister_entrees(self.tmp, text_mode=True), ["a.txt", "b.md", "c.MD"])

    def test_mode_pdf_ne_prend_que_les_pdf(self):
        for nom in ("a.txt", "b.md", "d.pdf"):
            self._touch(nom)
        self.assertEqual(lister_entrees(self.tmp, text_mode=False), ["d.pdf"])


class TestScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_detection(self):
        texte, scan, fax = (os.path.join(self.tmp, n) for n in ("t.pdf", "s.pdf", "f.pdf"))
        pdf_texte(texte)
        pdf_scan(scan)
        pdf_scan(fax, entete="Télécopie reçue le 03/10/2026 page 1/1")
        self.assertEqual(PdfProcessor(texte).pages_image_sans_texte(), [])
        self.assertEqual(PdfProcessor(scan).pages_image_sans_texte(), [0])
        self.assertEqual(PdfProcessor(fax).pages_image_sans_texte(), [0])

    def test_scan_signale_et_aucune_sortie(self):
        scan = os.path.join(self.tmp, "scan.pdf")
        sortie = os.path.join(self.tmp, "sortie.pdf")
        pdf_scan(scan)
        with open(sortie, "w") as f:
            f.write("ancienne sortie")  # une passe précédente ne doit pas survivre
        pl = AnonymizationPipeline.__new__(AnonymizationPipeline)  # sans moteurs : ils ne doivent pas servir
        r = pl.process_file(scan, sortie)
        self.assertEqual(r.status, "NON_TRAITE")
        self.assertIn("image sans texte : OCR nécessaire", r.error)
        self.assertFalse(os.path.exists(sortie))


if __name__ == "__main__":
    unittest.main()

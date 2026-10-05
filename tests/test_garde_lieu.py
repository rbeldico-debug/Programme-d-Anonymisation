import os
import tempfile
import unittest

from app.core.garde_lieu import type_de_montage, verifier_lieu


def _mountinfo(lignes):
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".mountinfo")
    f.write("\n".join(lignes) + "\n")
    f.close()
    return f.name


class TestGardeLieu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Un faux mountinfo : / en btrfs, et self.tmp/partage en sshfs (avec un espace échappé).
        self.partage = os.path.join(self.tmp, "mon partage")
        os.makedirs(self.partage)
        point = self.partage.replace(" ", "\\040")
        self.mi = _mountinfo([
            "22 1 0:21 / / rw,relatime - btrfs /dev/mapper/luks rw",
            f"90 22 0:50 / {point} rw,nosuid - fuse.sshfs pupitre:Claude-CachyOS rw",
        ])

    def tearDown(self):
        os.unlink(self.mi)

    def test_type_local(self):
        self.assertEqual(type_de_montage(self.tmp, self.mi), "btrfs")

    def test_type_distant_et_sous_dossier(self):
        self.assertEqual(type_de_montage(os.path.join(self.partage, "data"), self.mi), "fuse.sshfs")

    def test_entree_locale_acceptee(self):
        verifier_lieu(self.tmp, "d'entrée", self.mi)  # ne lève rien

    def test_sortie_inexistante_sous_sshfs_refusee(self):
        with self.assertRaises(RuntimeError) as c:
            verifier_lieu(os.path.join(self.partage, "data", "output"), "de sortie", self.mi)
        self.assertIn("fuse.sshfs", str(c.exception))

    def test_prefixe_homonyme_non_confondu(self):
        # « mon partage-bis » commence comme le point de montage mais n'est pas dessous.
        voisin = self.partage + "-bis"
        os.makedirs(voisin)
        verifier_lieu(voisin, "d'entrée", self.mi)


if __name__ == "__main__":
    unittest.main()

"""Garde-fou du LIEU des données : refuser de lire ou d'écrire des documents ailleurs que sur un disque local.

Pourquoi : un dossier qui ressemble à un dossier local peut être un MONTAGE RÉSEAU (sshfs, NFS, SMB…).
Lancé dans un tel dossier, l'outil déposerait les documents réels sur une autre machine, sans un mot.
C'est le cas concret qui a motivé ce module (05/10/2026) : sur le poste du praticien, ~/Claude-CachyOS
est le disque d'une machine virtuelle monté par sshfs ; les chemins par défaut `data/input` et
`data/output`, relatifs, y auraient atterri si l'outil avait été lancé depuis ce dossier.

On juge le TYPE de montage, pas le nom du dossier : dans la VM de développement, ce même dossier est un
disque local et y faire tourner des bancs SYNTHÉTIQUES est voulu ; vu du poste, c'est un montage sshfs, refusé.
Pas d'option pour passer outre : déplacer les données coûte moins cher qu'une fuite.
"""
import os

# Types de systèmes de fichiers refusés : tout ce qui n'est pas un disque de cette machine.
TYPES_DISTANTS = {
    "fuse.sshfs", "sshfs", "nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "virtiofs",
    "fuse.rclone", "fuse.gvfsd-fuse", "davfs", "fuse.davfs2", "afs", "ceph", "glusterfs",
}


def _decoder(champ: str) -> str:
    """/proc/self/mountinfo échappe espace, tabulation, saut de ligne et barre oblique inverse en octal."""
    return (champ.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def type_de_montage(chemin: str, mountinfo: str = "/proc/self/mountinfo") -> str:
    """Le type du système de fichiers qui porte `chemin` (le point de montage le plus long qui le contient)."""
    vrai = os.path.realpath(chemin)
    meilleur, type_fs = "", "inconnu"
    with open(mountinfo, encoding="utf-8") as f:
        for ligne in f:
            gauche, _, droite = ligne.partition(" - ")
            champs = gauche.split()
            if len(champs) < 5 or not droite:
                continue
            point = _decoder(champs[4])
            dedans = vrai == point or vrai.startswith(point.rstrip("/") + "/") or point == "/"
            if dedans and len(point) >= len(meilleur):
                meilleur, type_fs = point, droite.split()[0]
    return type_fs


def verifier_lieu(chemin: str, role: str, mountinfo: str = "/proc/self/mountinfo") -> None:
    """Lève RuntimeError si `chemin` (entrée ou sortie) n'est pas un dossier sur un disque local."""
    vrai = os.path.realpath(chemin)
    # Le dossier de sortie peut ne pas exister encore : on juge son parent existant le plus proche.
    sonde = vrai
    while not os.path.exists(sonde) and os.path.dirname(sonde) != sonde:
        sonde = os.path.dirname(sonde)
    type_fs = type_de_montage(sonde, mountinfo)
    if type_fs in TYPES_DISTANTS:
        raise RuntimeError(
            f"Dossier {role} refusé : {vrai} est sur un montage réseau ({type_fs}). "
            "Les documents ne doivent jamais quitter le disque local.")

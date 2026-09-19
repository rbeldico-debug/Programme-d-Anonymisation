import hashlib
import hmac
import re
from datetime import date, timedelta
from typing import Optional

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]

# Formes reconnues pour le DÉCALAGE (la détection, elle, vit dans config.yaml)
_NUMERIC = re.compile(r"^(\d{1,2})([/.-])(\d{1,2})\2(\d{4}|\d{2})$")
_LETTERS = re.compile(r"^(1er|\d{1,2})(\s+)([^\W\d]+)(\s+)(\d{4})$", re.IGNORECASE)


def _plain(word: str) -> str:
    """'Février' -> 'fevrier' : on compare les mois sans accent ni majuscule."""
    return word.lower().replace("é", "e").replace("û", "u")


def shift_days_from_key(patient_key: str) -> int:
    """
    Décalage en jours dérivé de la clé du patient : entier dans ±[30, 180], jamais 0.
    Même clé = même décalage : les intervalles entre deux dates d'un même patient sont conservés.
    """
    if not patient_key:
        raise ValueError("Clé patient vide : pas de décalage possible.")
    digest = hmac.new(patient_key.encode("utf-8"), b"decalage-dates", hashlib.sha256).digest()
    number = int.from_bytes(digest[:8], "big")
    magnitude = 30 + (number >> 1) % 151  # 30..180
    return magnitude if number & 1 else -magnitude


def shift_date_text(text: str, days: int) -> Optional[str]:
    """
    Décale une date COMPLÈTE écrite en français, en conservant son format.
    Retourne None si ce n'est pas une date complète valide (JJ/MM sans année, 31/02...) :
    l'appelant doit alors la masquer.
    """
    text = text.strip()

    m = _NUMERIC.match(text)
    if m:
        day_s, sep, month_s, year_s = m.groups()
        year = int(year_s)
        if len(year_s) == 2:
            # Pivot : « 25 » = 2025, « 65 » = 1965 (une date médicale n'est pas dans le futur)
            year += 2000 if year <= (date.today().year % 100) + 1 else 1900
        try:
            new = date(year, int(month_s), int(day_s)) + timedelta(days=days)
        except (ValueError, OverflowError):
            return None
        new_day = f"{new.day:02d}" if len(day_s) == 2 else str(new.day)
        new_month = f"{new.month:02d}" if len(month_s) == 2 else str(new.month)
        new_year = f"{new.year:04d}" if len(year_s) == 4 else f"{new.year % 100:02d}"
        return f"{new_day}{sep}{new_month}{sep}{new_year}"

    m = _LETTERS.match(text)
    if m:
        day_s, sp1, month_s, sp2, year_s = m.groups()
        plain_months = [_plain(name) for name in MONTHS]
        if _plain(month_s) not in plain_months:
            return None
        day = 1 if day_s.lower() == "1er" else int(day_s)
        try:
            new = date(int(year_s), plain_months.index(_plain(month_s)) + 1, day) + timedelta(days=days)
        except (ValueError, OverflowError):
            return None
        new_month = MONTHS[new.month - 1]
        if month_s[0].isupper():
            new_month = new_month.capitalize()
        new_day = "1er" if new.day == 1 else str(new.day)
        return f"{new_day}{sp1}{new_month}{sp2}{new.year}"

    return None

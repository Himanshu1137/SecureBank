"""Indian KYC helpers: mobile + Aadhaar format validation (Verhoeff checksum)."""
import hashlib
import re

from django.conf import settings

_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
      [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
      [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_ok(num):
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(base):
    c = 0
    for i, ch in enumerate(reversed(base)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def clean_phone(value):
    s = re.sub(r'[\s-]', '', str(value or ''))
    s = s[3:] if s.startswith('+91') else s[2:] if (s.startswith('91') and len(s) == 12) else s
    return s if re.fullmatch(r'[6-9]\d{9}', s) else None


def clean_aadhaar(value):
    s = re.sub(r'\s', '', str(value or ''))
    return s if re.fullmatch(r'[2-9]\d{11}', s) and verhoeff_ok(s) else None


def aadhaar_hash(aadhaar):
    return hashlib.sha256((settings.SECRET_KEY + aadhaar).encode()).hexdigest()

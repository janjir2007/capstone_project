"""Forgiving text matching for company names and fleet numbers (task 4.2b).

The oil changer types these by hand, so "говь  тээвэр ххк" must find the
company "Говь Тээвэр ХХК", and "ht-12" the fleet truck "HT-12".

Comparison happens in Python, not in SQL: Postgres lower()/ILIKE on Cyrillic
depends on the database locale (en_US.utf8 locally; the cloud DB is not
verified), while str.casefold() always handles Cyrillic, including Ө and Ү.
The tables involved are small (hundreds of companies, a few fleet trucks).

Plates are NOT normalized here: their rule lives only in src/common/plates.py
(``search_matches`` calls it).
"""

import re

from src.common.plates import normalize_plate

SEARCH_PHONE_MIN_DIGITS = 3  # «99» would match almost every phone; from 3 digits a phone part is useful
_PHONE_SEPARATORS = re.compile(r"[\s\-().+]")


def clean_company_name(name: str) -> str:
    """Name as stored: no leading/trailing spaces, runs of spaces become one.

    Case is kept as typed ("Говь Тээвэр ХХК" stays readable on the card).
    """
    return " ".join(name.split())


def company_key(name: str) -> str:
    """Comparison key: cleaned name, case ignored.

    "  говь   ТЭЭВЭР ххк " and "Говь Тээвэр ХХК" -> the same key.
    """
    return clean_company_name(name).casefold()


def fleet_no_key(identifier: str) -> str:
    """Comparison key for a fleet number: whitespace and dashes removed, case ignored.

    "ht 12", "HT12", "ht-12", "H-T 12" -> "ht12". Task 4.4 (D-043 follow-up): dashes
    are typed inconsistently, so "HT-12" and "HT12" are the same truck. Fleet numbers
    are unique only per company (D-005), so the company still separates trucks.
    """
    return "".join(identifier.split()).replace("-", "").casefold()


def phone_part_key(query: str) -> str | None:
    """Digits to look for inside driver phones, or None when the query is not a phone (part).

    "9911-00", "+976 9911 0002" -> "991100", "99110002". The country code is dropped only
    from a full 11-digit number (a 3-digit part "976" stays as typed). Letters -> None.
    """
    digits = _PHONE_SEPARATORS.sub("", query)
    if not digits.isdigit() or len(digits) < SEARCH_PHONE_MIN_DIGITS:
        return None
    return digits[3:] if digits.startswith("976") and len(digits) == 11 else digits


def search_matches(query: str, identifier_type: str, identifier: str, plate_normalized: str | None,
                   company_name: str, phones: set[str]) -> list[str]:
    """Why one vehicle matches a dashboard search (task 9.1): any of "plate", "fleet_no",
    "company", "phone"; [] = no match. Every test is "contains", so a part is enough:
    "1234" finds "1234 УБА", "говь" finds "Говь Тээвэр ХХК", "9911" finds phone 99110002.

    plate: normalize_plate on both sides (look-alike Latin letters, spaces, case).
    company / fleet_no: the same keys as lookup and POST /services (casefold, spaces).
    phone: digits only, in any driver phone this truck ever had (D-004).
    A blank query matches nothing here (the endpoint lists every truck instead).
    """
    if not query.strip():
        return []
    try:
        plate_key = normalize_plate(query)
    except ValueError:  # only separators typed ("-", ".")
        plate_key = None
    found = []
    if identifier_type == "plate" and plate_normalized and plate_key and plate_key in plate_normalized:
        found.append("plate")
    fleet_key = fleet_no_key(query)
    if identifier_type == "fleet_no" and fleet_key and fleet_key in fleet_no_key(identifier):
        found.append("fleet_no")
    if company_key(query) in company_key(company_name):
        found.append("company")
    phone_key = phone_part_key(query)
    if phone_key and any(phone_key in phone for phone in phones):
        found.append("phone")
    return found

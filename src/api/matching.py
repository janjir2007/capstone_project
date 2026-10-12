"""Forgiving text matching for company names and fleet numbers (task 4.2b).

The oil changer types these by hand, so "говь  тээвэр ххк" must find the
company "Говь Тээвэр ХХК", and "ht-12" the fleet truck "HT-12".

Comparison happens in Python, not in SQL: Postgres lower()/ILIKE on Cyrillic
depends on the database locale (en_US.utf8 locally; the cloud DB is not
verified), while str.casefold() always handles Cyrillic, including Ө and Ү.
The tables involved are small (hundreds of companies, a few fleet trucks).

Plates are NOT handled here: their rule lives only in src/common/plates.py.
"""


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

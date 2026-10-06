"""Plate normalization — the ONLY place plates are normalized (CLAUDE.md).

Used by the API (lookup + saving a service, task 4.2) and later by plate
recognition (task 3.4), so a plate typed by hand and a plate read from a photo
end up as the same database key (vehicles.plate_normalized).

Current rule (task 4.2): remove all whitespace, upper-case.
    "1234 уба" -> "1234УБА"
Task 3.4 adds the Latin/Cyrillic look-alike map and the format check
(open question 7: which letters really appear on Mongolian plates).
"""


def normalize_plate(raw: str) -> str:
    """Return the database key for a licence plate.

    Removes every whitespace character (spaces, tabs, non-breaking spaces) and
    upper-cases the rest. str.upper() handles Cyrillic, including Ө and Ү.

    Raises ValueError if nothing is left (a blank plate is never valid).
    """
    plate = "".join(raw.split()).upper()
    if not plate:
        raise ValueError("plate is empty")
    return plate

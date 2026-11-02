"""Tests for the Artlab core (task 9.6b-2): extract, status, bills, matching, transfers stub.

All data is SYNTHETIC (made-up plates 1234УБА / 5678ОНХ, phones 9911xxxx): the Artlab test DB has
no plates or phones in its descriptions (docs/artlab_api_notes.md §7), and real receipts are never
used in tests (RISK-06).
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date

import pytest

from src.artlab import status as S
from src.artlab.bills import ArtlabBill, parse_bill
from src.artlab.extract import extract, find_phones, find_plates
from src.artlab.matching import (
    BOTH,
    CONFLICT,
    MULTIPLE,
    NONE,
    PHONE,
    PLATE,
    Match,
    ServiceCandidate,
    match_bill,
    window,
)
from src.artlab.transfers import Transfer, parse_transfers, pay_later

D = date(2026, 10, 15)
LOAN = frozenset({"LOAN"})

# ---------------------------------------------------------------- extract


@pytest.mark.parametrize(
    "text, plates",
    [
        ("1234 УБА солих", ["1234УБА"]),
        ("1234-уба", ["1234УБА"]),                # lower case + dash
        ("1234.УБА", ["1234УБА"]),
        ("1234УБА", ["1234УБА"]),
        ("1234 УБA", ["1234УБА"]),                # Latin A typed for А
        ("1234 OHX", ["1234ОНХ"]),                # all-Latin look-alikes
        ("1234УБА99112233", ["1234УБА"]),         # plate glued to phone
        ("1234 УБА, дахиад 1234 уба", ["1234УБА"]),  # same plate twice -> once
        ("1234 УБА 5678 ОНХ", ["1234УБА", "5678ОНХ"]),
        ("9911 2233 тос", []),                    # phone's 2nd half + "oil": not a plate
        ("99112233 1234 УБА", ["1234УБА"]),       # phone first, then the plate: still found
        ("5000 тос", []),                         # "oil" is a stop-listed word
        ("5000 төг", []),                         # amount + tugrik, not a plate
        ("5000төг", []),
        ("тос 5000 төгрөг", []),                  # longer word: not a plate either
        ("12З4 УБА", []),                         # Cyrillic З typed for 3: no fix, phone fallback
        ("1O34 УБА", []),                         # letter O in the digits: no fix
        ("1234 ЖЖЖ", []),                         # Ж never seen on a plate (PLATE_LETTERS)
        ("99112233", []),
        ("", []),
        (None, []),
    ],
)
def test_find_plates(text, plates):
    assert find_plates(text) == plates


def test_latin_b_reads_as_cyrillic_ve_documented_limit():
    """normalize_plate maps Latin B -> В (look-alike), so 'uba' typed in Latin is 1234УВА, not УБА.
    plates.py is shared with OCR and is not changed here; the phone still matches (9.6b-2 note)."""
    assert find_plates("1234 uba") == ["1234УВА"]


@pytest.mark.parametrize(
    "text, phones",
    [
        ("утас 9911 2233", ["99112233"]),
        ("99112233", ["99112233"]),
        ("9911-2233", ["99112233"]),
        ("9911 2233, 8811 4455", ["99112233", "88114455"]),
        ("99112233 99112233", ["99112233"]),
        ("1234 УБА", []),
        ("123456789", []),                        # 9 digits: not a phone
        (None, []),
    ],
)
def test_find_phones(text, phones):
    assert find_phones(text) == phones


def test_extract_returns_only_plates_and_phones():
    found = extract("Бат жолооч 1234 УБА 9911 2233 тос 5000 төг")
    assert found.plates == ("1234УБА",) and found.phones == ("99112233",)
    assert {f.name for f in fields(found)} == {"plates", "phones"}  # no text, no name kept


# ---------------------------------------------------------------- status


def test_mixed_cash_and_loan_bill_owes_only_the_credit_part():
    split = S.split_payments([{"type": "CASH", "amount": 30000}, {"type": "LOAN", "amount": 50000}], LOAN)
    assert (split.paid_now, split.credit_amount, split.n_payments) == (30000, 50000, 2)
    assert S.bill_status(split) == S.UNPAID


@pytest.mark.parametrize(
    "payments, expected",
    [
        ([{"type": "CASH", "amount": 80000}], S.PAID),
        ([{"type": "NON_CASH_PAY_QPAY", "amount": 80000}, {"type": "NON_CASH_CARD", "amount": 1}], S.PAID),
        ([{"type": "LOAN", "amount": 80000}], S.UNPAID),
        ([{"type": "loan", "amount": 80000}], S.UNPAID),       # case-insensitive
        ([{"type": "LOAN", "amount": 0}, {"type": "CASH", "amount": 5}], S.PAID),  # zero credit = nothing owed
        ([], S.UNKNOWN),
        (None, S.UNKNOWN),
        ([{"type": "CASH", "amount": "bad"}], S.PAID),         # bad amount counts as 0, still a payment
    ],
)
def test_bill_status(payments, expected):
    assert S.bill_status(S.split_payments(payments, LOAN)) == expected


def test_credit_pay_types_from_env():
    assert S.credit_pay_types({}) == {"LOAN"}
    assert S.credit_pay_types({"ARTLAB_CREDIT_PAY_TYPES": " "}) == {"LOAN"}
    assert S.credit_pay_types({"ARTLAB_CREDIT_PAY_TYPES": "loan, credit_x"}) == {"LOAN", "CREDIT_X"}


@pytest.mark.parametrize(
    "bills, expected",
    [
        ([], S.UNKNOWN),
        ([S.PAID], S.PAID),
        ([S.PAID, S.PAID_LATER], S.PAID_LATER),
        ([S.PAID, S.UNPAID], S.UNPAID),
        ([S.PAID_LATER, S.UNKNOWN], S.UNKNOWN),
        ([S.UNPAID, S.UNKNOWN], S.UNPAID),
    ],
)
def test_service_status_rolls_up_bills(bills, expected):
    assert S.service_status(bills) == expected


def test_labels_cover_exactly_the_four_statuses():
    assert set(S.LABELS_MN) == set(S.STATUSES)
    assert S.LABELS_MN[S.PAID_LATER] == "Төлсөн (дараа)" and S.LABELS_MN[S.UNKNOWN] == "Тодорхойгүй"


# ---------------------------------------------------------------- bills


def raw_bill(**over) -> dict:
    """A synthetic Artlab bill row in the shape seen on the test DB (notes §5)."""
    bill = {
        "id": 104400000000000001, "num": "N1", "billDate": "2026-10-15", "type": "SALE_VAT",
        "status": "COMPLETE", "description": "1234 УБА 9911 2233", "totalGross": 80000,
        "payments": [{"type": "CASH", "name": "Бэлэн", "amount": 80000, "change": 0}],
        "dtls": [{"product": {"code": "OIL", "name": "Тос"}, "qty": 1, "agents": [{"name": "X"}]}],
        "terminal": {"code": "T1", "name": "Касс", "branch": {"code": "01", "name": "Салбар"}},
    }
    bill.update(over)
    return bill


def test_parse_bill_keeps_only_what_matching_needs():
    bill = parse_bill(raw_bill(), LOAN)
    assert bill == ArtlabBill(
        artlab_id=104400000000000001, bill_date=D, bill_type="SALE_VAT", bill_status="COMPLETE",
        total_gross=80000.0, paid_now=80000.0, credit_amount=0.0,
        plates=("1234УБА",), phones=("99112233",), payment_status=S.PAID,
    )
    kept = {f.name for f in fields(ArtlabBill)}
    assert not kept & {"description", "num", "dtls", "terminal", "name", "agents"}


def test_parse_mixed_loan_bill():
    bill = parse_bill(raw_bill(type="SALE", payments=[{"type": "CASH", "amount": 20000},
                                                      {"type": "LOAN", "amount": 60000}]), LOAN)
    assert bill is not None
    assert (bill.payment_status, bill.paid_now, bill.credit_amount) == (S.UNPAID, 20000, 60000)


@pytest.mark.parametrize(
    "over",
    [{"type": "PURCHASE"}, {"type": "SALE_VAT_RETURN"}, {"type": "MOVE"},
     {"status": "OPEN"}, {"status": "CANCEL"}],
)
def test_non_sales_are_skipped(over):
    assert parse_bill(raw_bill(**over), LOAN) is None


def test_bill_without_total_or_description():
    bill = parse_bill(raw_bill(totalGross=None, description=None), LOAN)
    assert bill is not None and bill.total_gross is None and bill.plates == () and bill.phones == ()


def test_tugrik_amount_in_description_is_no_plate():
    bill = parse_bill(raw_bill(description="тос 5000 төг, 9911 2233"), LOAN)
    assert bill is not None and bill.plates == () and bill.phones == ("99112233",)


@pytest.mark.parametrize("over", [{"id": None}, {"id": "abc"}, {"billDate": "15/10/2026"}, {"billDate": None}])
def test_malformed_bill_raises_without_data_in_message(over):
    with pytest.raises(ValueError) as err:
        parse_bill(raw_bill(**over), LOAN)
    assert "УБА" not in str(err.value) and "9911" not in str(err.value)


# ---------------------------------------------------------------- matching


def svc(sid: int, day: int, plate: str | None, phone: str | None) -> ServiceCandidate:
    return ServiceCandidate(sid, date(2026, 10, day), plate, phone)


S1 = svc(1, 15, "1234УБА", "99112233")
S2 = svc(2, 15, "5678ОНХ", "88114455")
FLEET = svc(3, 15, None, "77001122")  # fleet-number truck: no plate


@pytest.mark.parametrize(
    "plates, phones, cands, expected",
    [
        (["1234УБА"], ["99112233"], [S1, S2], Match(1, BOTH, None)),
        (["1234УБА"], [], [S1, S2], Match(1, PLATE, None)),
        ([], ["99112233"], [S1, S2], Match(1, PHONE, None)),                 # typo plate -> phone
        (["1234УВА"], ["99112233"], [S1, S2], Match(1, PHONE, None)),        # wrong letter -> phone
        (["1234УБА"], ["88114455"], [S1, S2], Match(None, None, CONFLICT)),  # plate S1, phone S2
        ([], ["77001122"], [FLEET, S1], Match(3, PHONE, None)),              # fleet truck by phone
        ([], [], [S1, S2], Match(None, None, NONE)),
        (["9999ААА"], ["11111111"], [S1, S2], Match(None, None, NONE)),
        (["1234УБА"], ["99112233"], [], Match(None, None, NONE)),
    ],
)
def test_match_rules(plates, phones, cands, expected):
    assert match_bill(D, plates, phones, cands) == expected


def test_window_is_plus_minus_one_day():
    for day, linked in ((13, False), (14, True), (15, True), (16, True), (17, False)):
        m = match_bill(D, ["1234УБА"], [], [svc(1, day, "1234УБА", None)])
        assert (m.service_id == 1) is linked, day
    assert window(D) == (date(2026, 10, 14), date(2026, 10, 16))


def test_two_services_same_plate_need_the_phone():
    """Same truck serviced on the 14th and the 16th (both within ±1 day), different drivers."""
    a, b = svc(10, 14, "1234УБА", "99112233"), svc(11, 16, "1234УБА", "88114455")
    assert match_bill(D, ["1234УБА"], [], [a, b]) == Match(None, None, MULTIPLE)
    assert match_bill(D, ["1234УБА"], ["88114455"], [a, b]) == Match(11, BOTH, None)


def test_two_services_same_phone_without_plate_is_multiple():
    """One driver brought two trucks: the phone alone cannot choose."""
    a, b = svc(20, 15, "1111ААА", "99112233"), svc(21, 15, "2222БББ", "99112233")
    assert match_bill(D, [], ["99112233"], [a, b]) == Match(None, None, MULTIPLE)
    assert match_bill(D, ["2222БББ"], ["99112233"], [a, b]) == Match(21, BOTH, None)


def test_unique_plate_wins_over_ambiguous_phone():
    other1, other2 = svc(30, 15, "3333ВВВ", "88114455"), svc(31, 15, "4444ГГГ", "88114455")
    assert match_bill(D, ["1234УБА"], ["88114455"], [S1, other1, other2]) == Match(1, PLATE, None)


def test_two_plates_in_one_receipt_is_multiple():
    assert match_bill(D, ["1234УБА", "5678ОНХ"], [], [S1, S2]) == Match(None, None, MULTIPLE)


def test_two_receipts_may_link_the_same_service():
    """Oil and filters on separate receipts (PM §4): matching is per bill, nothing is used up."""
    oil_receipt = match_bill(D, ["1234УБА"], [], [S1])
    filter_receipt = match_bill(D, [], ["99112233"], [S1])
    assert oil_receipt == Match(1, PLATE, None) and filter_receipt == Match(1, PHONE, None)


def test_receipt_to_link_end_to_end():
    bill = parse_bill(raw_bill(description="5678 онх, утас 8811-4455",
                               payments=[{"type": "LOAN", "amount": 80000}]), LOAN)
    assert bill is not None and bill.payment_status == S.UNPAID
    assert match_bill(bill.bill_date, bill.plates, bill.phones, [S1, S2]) == Match(2, BOTH, None)


# ---------------------------------------------------------------- transfers (stub)


def test_transfer_functions_are_stubs_until_artlab_sample():
    with pytest.raises(NotImplementedError, match="acc-txn"):
        parse_transfers({"value": []}, "127000000001")
    t = Transfer("k", D, "127000000001", 80000.0, ("1234УБА",), ())
    with pytest.raises(NotImplementedError):
        pay_later([], [t])

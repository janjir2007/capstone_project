# Artlab API v2: probe notes (task 9.6a)

Source: Artlab Postman collection "Artlab Cloud ERP - API v2 — шинэ бүтэц" (kept locally, not in git) plus
`scripts/artlab_probe.py` run against the **Artlab TEST account** on 2026-11-02.
"Documented" means it comes from the collection. "Observed" means the probe measured it. Only GET requests and
`POST /auth/login` were sent (D-114).

```
.venv/bin/python -m scripts.artlab_probe --from 2025-01-01 --to 2025-04-30
```

## 1. Auth

| Item | Value | Source |
| --- | --- | --- |
| Login | `POST /auth/login` body `{username, password, type: "api"}` | documented + observed |
| Token | In the `Authorization` **response header**. It already starts with `Bearer `, so it is sent back unchanged | observed |
| Login body | keys `connId`, `type`, `userId` | observed |
| Token format | JWT, claims `conn, exp, iat, sub, type` | observed (decoded, not verified) |
| **Token lifetime** | **60 min** (`exp − iat`). The docs also say 1 h, and that a non-expiring token can be requested. We should **not** ask for one (RISK-22) | observed + documented |
| Expired token | docs: `400` ("токены хугацаа дууссан") or `401`. Not observed yet | documented |
| `GET /auth/check` | `{value: true, success: true}` | observed |
| `GET /auth/connections` | 1 connection; fields `id, code, name, companyId, company{id,name}` | observed |

Sync robot rule: log in once per run (every 30 min). The token is never stored to disk and never logged.

## 2. Response format

Every response so far is wrapped: `{"value": <list or object>, "success": true}`.
Empty result: the docs say `204 No content`. The probe treats 204 or an empty body as an empty list.

## 3. Paging (observed)

| Header (request) | Effect |
| --- | --- |
| `X-Limit` | page size. **Default 25, max 500.** Larger values are silently capped to 500 (the response `x-limit` header says 500) |
| `X-Offset` | start index. Offsets 0 and 5 gave disjoint pages |
| `X-Summary: 1` | empty list + `X-Total-Records` header = total count for the same filters |

Response headers: `x-limit`, `x-offset`, `x-offset-next` (`X-Offset-Prev` is documented but was not returned on page 1).
**Order: newest first** (`billDate` descending). On the test DB page 1 is 2026-08-10 and the last page is 2024-05-13.
Sync loop: `X-Limit: 500`, keep going until a page has fewer than 500 rows.

## 4. Date filters (observed)

| Endpoint | `from` | `to` | Evidence |
| --- | --- | --- | --- |
| `/pos/bills` | ✅ works (**not in the collection**, which only lists `to`) | ✅ works | all 1348 → `to=2026-08-09` 135; `from=2025-01-01&to=2025-04-30` 55, all in range; `from=to=2026-08-10` 1213 (= 1348 − 135) |
| `/invoices` | ✅ works | ✅ works | Sep 2024 → 1 (the only invoice), Oct 2026 → 0 |

Both are inclusive `YYYY-MM-DD`. `startDate` and `beginDate` are **ignored** on `/pos/bills` (same total, rows outside the range).
Other documented bill filters: `type`, `status`, `branch`, `entity` (not tested).

## 5. Bills: `GET /pos/bills?withDtl=1`

Without `withDtl=1`, the rows have no `dtls`.

Fields seen (test DB, Q1 2025, 55 bills):

```
id (int, unique)  num  billDate  createdAt  modifiedAt  type  status  description (key often absent)
terminal{code,name,branch{code,name}}
totalQty totalPrice totalDiscount totalVat totalCct totalGross
dtls[]{ordr, product{code,name,isService,measureCode}, qty, unitPrice, totalPrice, discount, vat, cct, gross, isVat, isCct, agents[]{code,name,amount}}
payments[]{type, name, amount, change}
```

- **No customer / entity field on list rows.** The bill-get docs mention `entity`, but `GET /pos/bills/:id` is
  not on our allow-list and was not called. To check later whether a single bill has it, add only that GET.
- **`num` is not unique**: 62 distinct values over 135 bills (2024-05..2025-04), and 1210 over 1213 on 2026-08-10. Use **`id`** as the key.
- `type` values (`/pos/bills/types`): SALE_VAT, SALE, OUTCOME, PURCHASE, INCOME, SALE_VAT_RETURN, SALE_RETURN,
  PURCHASE_RETURN, MOVE, RESERVE, RESERVE_RETURN, RESERVE_SALE_VAT, RESERVE_SALE. Seen on the test DB: SALE_VAT, SALE, PURCHASE,
  PURCHASE_RETURN, SALE_VAT_RETURN.
- `status` values: OPEN, COMPLETE, CANCEL. Only COMPLETE was seen.
- Payments per bill: 0 / 1 / 2 (Q1 2025: 16 bills with 0 payments, and 15 are PURCHASE/PURCHASE_RETURN. Probably the same bills, not cross-checked. 2026-08-10: 18 bills with 2 payments).

**Payment types seen** (`payments[].type`):

| type | Q1 2025 (55 bills) | 2026-08-10 (first 1000 bills) |
| --- | --- | --- |
| CASH | 38 / 6,658,000 | 130 / 2,026,600 |
| NON_CASH_CARD | 1 / 1,324,000 | 530 / 9,431,150 |
| NON_CASH_PAY_QPAY | – | 352 / 6,477,400 |
| NON_CASH_SEND | – | 3 / 65,000 |
| NON_CASH_PAY_TOKI | – | 1 / 24,000 |

(count / amount sum, MNT.) Needs verification: which `type` stands for a **credit / unpaid** sale ("тооцоотой").
`SALE` is named «Зарлага /Тооцоотой/», so a credit sale may be a `SALE` bill with no payment. None was seen in this sample.

## 6. Invoices: `GET /invoices`

Test DB holds **1 invoice** (2024-09-18, status `open`; it looks like the collection's sample).
Fields: `id invoiceNum invoiceDate startDate endDate status isVat isCct vatInc cctInc totalQty totalPrice
totalDiscount totalVat totalCct totalGross createdAt customer{code,name}`. `description` and `dtls` were absent on that row.
Status values (documented): `open`, `closed` (paid), `canceled`. **There is no paid-amount field**, only the status.

## 7. Descriptions on the test DB

Masked shapes only (digit→9, Cyrillic→А, Latin→a):
- 2026-08-10: all 1213 look like `aaaaaa АААААААА: 999…`, which reads as a system/import note.
- 2024-05..2025-04: 55 of 135 have one: `aaaaaa АААААААААА` (41), `ААААААА` (14).

**No plate and no phone in any description.** So the test DB **cannot validate matching**. The plate/phone finders are
unit-tested on synthetic text only.

## 8. Matching rule (bill → our service), PM-accepted 2026-11-02

Ari confirms the practice: the oil changer types **both plate and phone** into the receipt `description`.
Our service records store the driver phone. The rule applies to bills with `type ∈ {SALE_VAT, SALE}` and
`status = COMPLETE`. Returns, purchases and moves are ignored for now.

1. **Plate.** Find `4 digits + 3 Cyrillic letters` in the description (any spacing/dash/case) and normalize it with
   `src/common/plates.normalize_plate` + `is_valid_plate`. Look for a service with the same `plate_normalized` and
   `service_date` within **±1 day** of `billDate`.
2. **Else phone.** Find an 8-digit number (`9911 2233` / `9911-2233`) and match it against the service's driver
   phone, in the same ±1 day window.
3. **Else unmatched**, shown as **«Тодорхойгүй»**. There is no same-day + amount step, because we store no prices.

Confidence:
- **High**: plate and phone both point to the same single service.
- **Plate only** or **phone only**: one rule found exactly one service.
- **Unmatched («Тодорхойгүй»)**: nothing found, several candidates, or plate and phone point to different services.
  These are never guessed.

Rules:
- One bill links to at most one service (UNIQUE `artlab_id` in `service_payments`).
- Known false positive: `5000 төг` reads as plate `5000ТӨГ`. It is stop-listed. Watch for more on real data.
- The test DB has no plates/phones in descriptions (§7). The first real check is on real bills, run by Ari, summaries only.

## 8b. Note for 9.6b: later payments (bank transfers)

Credit customers pay later by **bank transfer**, with the plate/phone in the transfer text. The candidate source
is `POST /report/acc-txn` («Дансны хуулга», Report → Account transaction).
**Do NOT call it yet.** It is a POST, so it is not on the allow-list. We are waiting for Artlab to confirm two things:
that it is read-only, and that it returns the transfer description. Once confirmed, it gets added as a single named exception, with a test.

## 8c. Probe 9.6b-1: payment methods + acc-txn (test DB, 2026-11-02)

```
.venv/bin/python -m scripts.artlab_probe --section paymethods
.venv/bin/python -m scripts.artlab_probe --section acc-txn --account 127000000001 --from 2024-01-01 --to 2026-11-02
```

Allow-list now: GET `/pos/paymethods` and `/pos/paymethods/types` were added. POST is `/auth/login` plus `/report/acc-txn` (Artlab confirmed
read-only). The acc-txn body is built in `ArtlabClient.acc_txn()` from exactly `accountCodes` (digits only),
`startDate` and `endDate` (YYYY-MM-DD). The client has no generic POST.

**Payment methods** (`GET /pos/paymethods`, 9 rows, fields `id, name, type`). These are company settings, not personal data:

| id | name | type |
| --- | --- | --- |
| 1 | Бэлэн | CASH |
| 2 | Карт | NON_CASH |
| 3 | Мобайл | NON_CASH |
| **4** | **Зээл** | **LOAN** |
| 76319565209409539 | QPAY | NON_CASH_PAY |
| 88525920677673985 | NON_CASH_CARD | NON_CASH_CARD |
| 104333378544483329 | NON_CASH_PAY_QPAY | NON_CASH_PAY_QPAY |
| 104333547737725953 | NON_CASH_SEND | NON_CASH_SEND |
| 104333577398533121 | NON_CASH_PAY_TOKI | NON_CASH_PAY_TOKI |

`/pos/paymethods/types` lists 15 types: CASH, NON_CASH, NON_CASH_CARD, NON_CASH_POS_MINU, NON_CASH_SEND,
NON_CASH_PAY, NON_CASH_PAY_SOCIALPAY / QPAY / MONPAY / TOKI / POCKET / STOREPAY / OMNI / HIPAY, **LOAN «Зээл»**.
Ids go above 2^53. That is fine in Python and in Postgres `BIGINT`, but a JavaScript client needs them as strings (`js-response-modify`).

**Credit code = `LOAN`.** Bill `payments[].type` carries the payment-method type
(e.g. `CASH` with `name` «Бэлэн», `LOAN` with «Зээл»). Over all 1348 test bills: NON_CASH_CARD 637, NON_CASH_PAY_QPAY 452,
CASH 260, NON_CASH_SEND 3, NON_CASH_PAY_TOKI 1, **LOAN 1**. The one LOAN bill (2024-09-13) has type `SALE`
(«Зарлага /Тооцоотой/»), status COMPLETE and **3 payments; the LOAN part ≠ totalGross**. That is a real mixed bill, which supports
PM decision 6(a): compare a later transfer to the **credit amount**, not the gross. That bill has no customer/entity field
either. Suggested `.env`: `ARTLAB_CREDIT_PAY_TYPES=LOAN`. The accountant should confirm that Geo-Expert's credit sales use it.

**acc-txn** (`POST /report/acc-txn`, account `127000000001`):
- HTTP 200 in about 0.85 s. Response `{"value": [], "success": true}` for Aug 2026 and also for **2024-01-01..2026-11-02**.
- Response headers include `x-limit` / `x-offset`, so the report probably pages like the lists (needs verification once there are rows).
- **A made-up code (`999999999999`) also returns 200 with an empty list.** A wrong account code therefore looks the same as
  "no transfers". The sync must flag "0 rows for N days" in `sync_runs` instead of trusting an empty result.
- **Row fields are still unknown.** 127000000001 is Artlab's example code and has no transactions in the test DB. The API
  offers no read-only GET that lists account codes; trial balance would, but it is not on the allow-list.

**Blocking for the transfer parser (9.6b-2):** we need one account code **that has transactions in the test DB**
(from Artlab, or the bank/receivable account the accountant will use), so that the `--section acc-txn` probe can
show the row fields: id / date / amount / sign / description. Until then the parser can't be written against real fields.

## 8d. Code (task 9.6b-2)

| Module | Job |
| --- | --- |
| `src/artlab/client.py` | read-only client (allow-list, acc-txn fixed body), moved from the probe |
| `src/artlab/extract.py` | plates + phones from a description; the text is dropped |
| `src/artlab/bills.py` | Artlab bill → stored fields (completed SALE_VAT / SALE only) |
| `src/artlab/status.py` | Төлсөн / Төлөөгүй (LOAN) / Тодорхойгүй per bill; roll-up per service |
| `src/artlab/matching.py` | plate → phone, ±1 day, confidence both / plate / phone, else none / multiple / conflict |
| `src/artlab/transfers.py` | **stub**: «Төлсөн (дараа)» from acc-txn, until Artlab sends a sample |
| `src/data/migrations/008_artlab.*.sql` | artlab_bills, artlab_transfers, sync_runs |

Extraction limits found while testing (synthetic text):
- `9911 2233 тос`: the 2nd half of a phone is never read as plate digits. `ТОС` (oil) and `ТӨГ` (tugrik) are
  stop-listed, so a real plate ending in them falls back to the phone.
- Latin `b`/`B` is read as Cyrillic **В** by the shared `normalize_plate` (look-alike rule), so a plate typed
  `1234 uba` becomes 1234УВА and falls back to the phone. `plates.py` is unchanged because OCR shares it.
- Digit typos (`12З4`, `1O34`) are not fixed, so those also fall back to the phone.

Smoke run on the test DB: 1,348 bills → 1,332 completed sales: 1,329 paid, 1 unpaid (the LOAN bill), 2 unknown (no payment),
0 with a plate or phone (system-note descriptions, so no false positives either).

## 9. Open questions for Artlab

1. ~~Which type marks a credit sale?~~ `LOAN` (§8c). Still open: a **test-DB account code with transactions**
   for acc-txn, and whether its rows carry the bank-transfer description (§8b, §8c).
2. Does `GET /pos/bills/:id` carry `entity` (customer) when list rows do not?
3. A rate limit number for `429`.
4. Earlier safeguard questions (IP restriction, separate API user, activity log) still stand (§4 PROJECT_STATE).

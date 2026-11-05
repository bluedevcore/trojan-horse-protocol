"""UK VAT helpers: VAT codes, VAT number check digits and the 9-box VAT
return workings. Deterministic; no AI.

Internal VAT codes (mapped to each accounting system's tax codes in exports.py):
    S  standard rate 20%      R  reduced rate 5%      Z  zero rate 0%
    E  exempt                 O  no VAT / outside scope / not reclaimable
    RC reverse charge (overseas services: VAT in both box 1 and box 4)
"""

from __future__ import annotations

import re

import pandas as pd

VAT_CODES = {"S": 20.0, "R": 5.0, "Z": 0.0, "E": 0.0, "O": 0.0, "RC": 20.0}
CODE_LABELS = {"S": "Standard 20%", "R": "Reduced 5%", "Z": "Zero rated", "E": "Exempt", "O": "No VAT",
               "RC": "Reverse charge 20%"}
_ALIASES = {"20": "S", "20%": "S", "T1": "S", "STANDARD": "S", "20.0% S": "S", "5": "R", "5%": "R", "T5": "R",
            "REDUCED": "R", "0": "Z", "0%": "Z", "T0": "Z", "ZERO": "Z", "ZERO RATED": "Z", "T2": "E", "EXEMPT": "E",
            "T9": "O", "NO VAT": "O", "NONE": "O", "OUTSIDE SCOPE": "O", "N/A": "O", "": "",
            "REVERSE CHARGE": "RC", "RC": "RC"}


def normalise_code(value) -> str:
    """Accept S/R/Z/E/O/RC, rates (20, 5%), Sage codes (T1) and words."""
    text = str(value or "").strip().upper()
    if text in VAT_CODES:
        return text
    return _ALIASES.get(text, _ALIASES.get(text.replace(".0", ""), ""))


def code_for_rate(rate: float, *, zero_default: str = "Z") -> str:
    if abs(rate - 20) < 0.6:
        return "S"
    if abs(rate - 5) < 0.6:
        return "R"
    if abs(rate) < 0.01:
        return zero_default
    return "S" if rate > 12 else "R"


def check_gb_vat_number(number: str) -> bool | None:
    """True if a GB VAT number passes HMRC's check-digit test (mod 97 or 9755),
    False if it fails, None if there is no number to check."""
    s = re.sub(r"[^0-9A-Z]", "", str(number or "").upper())
    if not s:
        return None
    if s.startswith("GB"):
        s = s[2:]
    elif s.startswith("XI"):  # Northern Ireland numbers use the same check
        s = s[2:]
    if re.fullmatch(r"(GD|HA)\d{3}", s):  # government departments / health authorities
        return True
    if len(s) == 12 and s.isdigit():  # branch traders: 9 digits + 3-digit branch
        s = s[:9]
    if not re.fullmatch(r"\d{9}", s):
        return False
    total = sum(int(d) * w for d, w in zip(s[:7], (8, 7, 6, 5, 4, 3, 2))) + int(s[7:])
    return total % 97 == 0 or (total + 55) % 97 == 0


def format_vat_number(number: str) -> str:
    s = re.sub(r"[^0-9A-Z]", "", str(number or "").upper())
    if s.startswith("GB") and len(s) == 11:
        return f"GB {s[2:5]} {s[5:9]} {s[9:]}"
    return str(number or "")


def make_gb_vat_number(seven_digits: str) -> str:
    """Build a check-digit-valid GB number from 7 digits (used for synthetic data)."""
    total = sum(int(d) * w for d, w in zip(seven_digits, (8, 7, 6, 5, 4, 3, 2)))
    check = (-total) % 97
    return f"GB{seven_digits}{check:02d}"

# ------------------------------------------------------------- VAT return

PURCHASE_KINDS = {"bill": 1, "supplier_credit": -1, "card_expense": 1, "expense_claim": 1}
SALES_KINDS = {"sales_invoice": 1, "sales_credit": -1}


def vat_return(entries: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, *, include_held: bool = False) -> pd.DataFrame:
    """Draft 9-box workings from coded entries dated in the period (accrual basis).

    Entries need columns: kind, date, net, vat, vat_code, status.
    """
    cols = ["Box", "Description", "Amount (£)", "How it is worked out"]
    if entries is None or entries.empty:
        return pd.DataFrame(columns=cols)
    e = entries[(entries["date"] >= start) & (entries["date"] <= end)]
    if not include_held:
        e = e[e["status"] == "Ready"]
    sign_s = e["kind"].map(SALES_KINDS).fillna(0)
    sign_p = e["kind"].map(PURCHASE_KINDS).fillna(0)
    in_scope = e["vat_code"] != "O"
    rc = e["vat_code"] == "RC"
    rc_vat = (e["net"] * 0.20).round(2)
    box1 = float((e["vat"] * sign_s).sum() + (rc_vat * sign_p)[rc].sum())
    box2 = 0.0
    box4 = float((e["vat"] * sign_p)[e["vat_code"].isin(["S", "R"])].sum() + (rc_vat * sign_p)[rc].sum())
    box6 = float((e["net"] * sign_s)[in_scope].sum() + (e["net"] * sign_p)[rc].sum())
    box7 = float((e["net"] * sign_p)[in_scope].sum())
    rows = [
        (1, "VAT due on sales and other outputs", box1, "Output VAT on sales invoices, plus notional VAT on reverse-charge purchases"),
        (2, "VAT due on acquisitions from the EU (NI only)", box2, "Not used (Northern Ireland goods only)"),
        (3, "Total VAT due (box 1 + box 2)", box1 + box2, "Box 1 + box 2"),
        (4, "VAT reclaimed on purchases and other inputs", box4, "Input VAT on standard and reduced-rate purchases (excludes blocked VAT), plus reverse-charge VAT"),
        (5, "Net VAT to pay HMRC (or reclaim)", box1 + box2 - box4, "Box 3 − box 4"),
        (6, "Total value of sales, excluding VAT", box6, "Net sales in scope of VAT, plus reverse-charge purchases"),
        (7, "Total value of purchases, excluding VAT", box7, "Net purchases in scope of VAT (excludes 'No VAT' items such as wages)"),
        (8, "Supplies of goods to the EU (NI only)", 0.0, "Not used"),
        (9, "Acquisitions of goods from the EU (NI only)", 0.0, "Not used"),
    ]
    out = pd.DataFrame(rows, columns=cols)
    out["Amount (£)"] = out["Amount (£)"].round(2)
    whole = out["Box"].isin([6, 7, 8, 9])
    out.loc[whole, "Amount (£)"] = out.loc[whole, "Amount (£)"].apply(lambda v: float(int(v)))  # HMRC: whole pounds
    return out

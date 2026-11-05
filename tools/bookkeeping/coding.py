"""Nominal coding: which account (and VAT code) each entry goes to.

Order of precedence, first hit wins:
    1. the supplier list (default account / VAT code per supplier)
    2. keyword rules from config (``coding.rules``: regex -> account)
    3. Claude, choosing only from the chart of accounts (see ai.py)
    4. the fallback account (``coding.fallback_account``, e.g. Suspense)
Claude's low-confidence choices become human checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from tools.bookkeeping.matching import name_similarity
from tools.bookkeeping.vat import check_gb_vat_number, format_vat_number, normalise_code


@dataclass
class Chart:
    accounts: pd.DataFrame  # code, name, type, description

    @property
    def names(self) -> list[str]:
        return self.accounts["name"].tolist()

    def has(self, name: str) -> bool:
        return name in set(self.names)

    def code(self, name: str) -> str:
        row = self.accounts[self.accounts["name"] == name]
        return str(row["code"].iloc[0]) if not row.empty and "code" in row else ""

    def resolve(self, value: str) -> str | None:
        """Accept an account name or code, case-insensitive."""
        value = str(value or "").strip()
        if not value:
            return None
        for name in self.names:
            if name.lower() == value.lower():
                return name
        if "code" in self.accounts:
            hit = self.accounts[self.accounts["code"].astype(str) == value]
            if not hit.empty:
                return hit["name"].iloc[0]
        return None

    def for_prompt(self, types: list[str] | None = None) -> list[dict]:
        acc = self.accounts
        if types and "type" in acc:
            acc = acc[acc["type"].str.lower().isin([t.lower() for t in types])]
        return [{"account": r["name"], **({"code": str(r["code"])} if r.get("code") else {}),
                 **({"use_for": r["description"]} if r.get("description") else {})}
                for r in acc.to_dict("records")]


def chart_from_frame(df: pd.DataFrame) -> Chart:
    acc = df.copy()
    for col in ("code", "type", "description"):
        if col not in acc:
            acc[col] = ""
    acc = acc[acc["name"].astype(str).str.strip() != ""].drop_duplicates("name")
    return Chart(acc[["code", "name", "type", "description"]].reset_index(drop=True))


@dataclass
class SupplierBook:
    suppliers: pd.DataFrame
    threshold: float = 0.85

    def find(self, name: str) -> dict | None:
        if self.suppliers is None or self.suppliers.empty or not name:
            return None
        best, best_score = None, 0.0
        for rec in self.suppliers.to_dict("records"):
            score = name_similarity(name, rec.get("name", ""))
            if score > best_score:
                best, best_score = rec, score
        return best if best_score >= self.threshold else None


@dataclass
class Code:
    account: str
    vat_code: str = ""
    coded_by: str = ""  # supplier list | rule | Claude | fallback
    confidence: str = "high"
    reason: str = ""
    receipt_needed: bool = True


@dataclass
class Rules:
    rules: list[dict] = field(default_factory=list)

    def match(self, text: str) -> dict | None:
        for rule in self.rules:
            if re.search(rule["match"], str(text or ""), re.I):
                return rule
        return None


def code_from_supplier(rec: dict | None, chart: Chart) -> Code | None:
    if not rec:
        return None
    account = chart.resolve(rec.get("default_account", ""))
    if not account:
        return None
    return Code(account, normalise_code(rec.get("vat_code", "")), "supplier list", "high",
                f"Default account for {rec.get('name')} on the supplier list")


def code_from_rules(text: str, rules: Rules, chart: Chart) -> Code | None:
    rule = rules.match(text)
    if not rule:
        return None
    account = chart.resolve(rule.get("account", ""))
    if not account:
        return None
    return Code(account, normalise_code(rule.get("vat_code", "")), "rule", "high",
                rule.get("reason") or f"Keyword rule “{rule['match']}”", bool(rule.get("receipt_needed", True)))


def supplier_vat_checks(doc: dict, supplier: dict | None) -> list[tuple[str, str]]:
    """VAT-number and bank-detail checks for one supplier document."""
    out: list[tuple[str, str]] = []
    vat_shown = (doc.get("vat_total") or 0) > 0.009
    number = doc.get("counterparty_vat_number", "")
    valid = check_gb_vat_number(number) if number and number[:2] in ("GB", "XI") or (number and number.isdigit()) else None
    if vat_shown and doc.get("currency", "GBP") == "GBP":
        if not number:
            on_file = (supplier or {}).get("vat_number", "")
            extra = "" if on_file else " and the supplier list has no VAT number for them either"
            out.append(("vat_without_number", f"£{doc['vat_total']:,.2f} VAT is charged but no VAT registration number "
                                              f"is shown{extra}, so it is not a valid VAT invoice."))
        elif valid is False:
            out.append(("vat_number_invalid", f"VAT number {format_vat_number(number)} fails HMRC's check-digit test, so the £"
                                              f"{doc['vat_total']:,.2f} VAT may not be reclaimable."))
    if supplier and number and supplier.get("vat_number"):
        if re.sub(r"\W", "", supplier["vat_number"]).upper() != number.upper() and valid is not False:
            out.append(("vat_number_mismatch", f"VAT number on the invoice ({format_vat_number(number)}) differs from the supplier list "
                                               f"({supplier['vat_number']})."))
    if supplier and (doc.get("bank_sort_code") or doc.get("bank_account_number")):
        file_sc = re.sub(r"\D", "", str(supplier.get("sort_code", "")))
        file_ac = re.sub(r"\D", "", str(supplier.get("account_number", "")))
        doc_sc, doc_ac = doc.get("bank_sort_code", ""), doc.get("bank_account_number", "")
        if (file_sc or file_ac) and ((doc_sc and doc_sc != file_sc) or (doc_ac and doc_ac != file_ac)):
            out.append(("bank_details_changed",
                        f"Bank details on the document (sort code {_sc(doc_sc)}, account {_mask(doc_ac)}) differ from "
                        f"the supplier list (sort code {_sc(file_sc)}, account {_mask(file_ac)}). This is a common "
                        f"invoice-fraud pattern."))
    return out


def _sc(s: str) -> str:
    return f"{s[:2]}-{s[2:4]}-{s[4:]}" if len(s) == 6 else (s or "none")


def _mask(s: str) -> str:
    return f"••••{s[-4:]}" if s else "none"

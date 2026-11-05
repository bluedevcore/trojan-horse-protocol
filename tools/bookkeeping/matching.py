"""Deterministic matching: card/bank transactions to receipts and invoices,
supplier statements to the documents received. No AI.

Scoring for a candidate pair (higher is better):
    reference found in the description   +3
    amounts equal (within 1p)            +2
    amounts close (tip / part refund)    +0.5
    name similarity (0–1)                +name score
    dates close                          +0.5 × (1 − days apart / window)
Pairs are assigned greedily, best score first, one-to-one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import pandas as pd

from tools.bookkeeping.tables import norm_name

_DESCRIPTOR_NOISE = re.compile(
    r"^(sq|sumup|zettle|izettle|paypal|pp|sp|crv|ztl|amzn mktp|www|card payment to|pos|contactless)\s*\*?\s*|"
    r"\b(gbr|gb|uk|london|telford|shrewsbury|birmingham|online|ltd|limited)\b|\d{2,}|\.com|\.co\.uk|\*", re.I)


def clean_descriptor(text: str) -> str:
    """'SQ *THE COPPER KETTLE TELFORD GB' -> 'copper kettle'."""
    s = str(text or "")
    for _ in range(2):
        s = _DESCRIPTOR_NOISE.sub(" ", s)
    return norm_name(s)


def name_similarity(a: str, b: str) -> float:
    """0..1 similarity of two counterparty names (card descriptors cleaned first)."""
    x, y = clean_descriptor(a), clean_descriptor(b)
    if not x or not y:
        return 0.0
    tx, ty = set(x.split()), set(y.split())
    overlap = len(tx & ty) / min(len(tx), len(ty))
    joined = SequenceMatcher(None, x.replace(" ", ""), y.replace(" ", "")).ratio()
    contains = 0.9 if (x.replace(" ", "") in y.replace(" ", "") or y.replace(" ", "") in x.replace(" ", "")) else 0.0
    return round(max(overlap, joined, contains), 3)


@dataclass
class MatchSettings:
    date_window_days: int = 7
    exact_tolerance: float = 0.01
    near_abs: float = 10.0  # amounts this close (or near_pct) can match when the names agree
    near_pct: float = 0.15
    min_name_score: float = 0.6

    @classmethod
    def from_config(cls, cfg: dict | None) -> "MatchSettings":
        cfg = cfg or {}
        return cls(**{k: cfg[k] for k in cls.__dataclass_fields__ if k in cfg})


def _days(a, b) -> int | None:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    return abs(int((pd.Timestamp(a) - pd.Timestamp(b)).days))


def pair_score(*, left_amount: float | None, right_amount: float | None, left_name: str, right_name: str,
               left_date, right_date, settings: MatchSettings, reference: str = "", haystack: str = "",
               amounts_comparable: bool = True) -> dict | None:
    """Score one candidate pair, or None if it cannot be a match."""
    days = _days(left_date, right_date)
    if days is not None and days > settings.date_window_days:
        return None
    name = name_similarity(left_name, right_name)
    ref_hit = bool(reference) and len(reference) >= 4 and reference.lower().replace(" ", "") in haystack.lower().replace(" ", "")
    diff = None
    exact = near = False
    if amounts_comparable and left_amount is not None and right_amount is not None:
        diff = round(left_amount - right_amount, 2)
        exact = abs(diff) <= settings.exact_tolerance
        near = not exact and abs(diff) <= max(settings.near_abs, settings.near_pct * abs(right_amount))
    if not (ref_hit or (exact and (name >= 0.3 or (days is not None and days <= 3)))
            or ((near or not amounts_comparable) and name >= settings.min_name_score)):
        return None
    score = 3 * ref_hit + 2 * exact + 0.5 * near + name
    if days is not None:
        score += 0.5 * (1 - days / max(settings.date_window_days, 1))
    return {"score": round(score, 3), "difference": diff, "exact": exact, "near": near, "name_score": name,
            "days_apart": days, "reference_hit": ref_hit}


def greedy_assign(candidates: list[tuple[str, str, dict]]) -> list[tuple[str, str, dict]]:
    """Best score first, each left and right id used at most once."""
    used_l, used_r, out = set(), set(), []
    for lid, rid, info in sorted(candidates, key=lambda c: (-c[2]["score"], c[0], c[1])):
        if lid in used_l or rid in used_r:
            continue
        used_l.add(lid)
        used_r.add(rid)
        out.append((lid, rid, info))
    return out

# ------------------------------------------------------------------ card


def match_card_to_documents(txns: pd.DataFrame, docs: list[dict], settings: MatchSettings) -> list[tuple[str, str, dict]]:
    """Card spend (``txn_id, date, description, amount`` with money out positive,
    optional ``original_currency``/``original_amount``) against receipts and
    paid invoices (gross in the document's currency)."""
    candidates = []
    for t in txns.itertuples(index=False):
        for d in docs:
            if d.get("gross_total") is None:
                continue
            doc_amount = d["gross_total"]
            comparable = d.get("currency", "GBP") == "GBP"
            left_amount = t.amount
            orig_cur = str(getattr(t, "original_currency", "") or "").upper()
            orig_amt = getattr(t, "original_amount", None)
            if not comparable and orig_cur == d.get("currency") and orig_amt is not None and not pd.isna(orig_amt):
                left_amount, comparable = abs(float(orig_amt)), True
            info = pair_score(left_amount=left_amount, right_amount=doc_amount, left_name=t.description,
                              right_name=d.get("counterparty", ""), left_date=t.date, right_date=d.get("document_date"),
                              settings=settings, reference=d.get("document_number", ""), haystack=str(t.description),
                              amounts_comparable=comparable)
            if info:
                info["foreign"] = d.get("currency", "GBP") != "GBP"
                candidates.append((t.txn_id, d["doc_id"], info))
    return greedy_assign(candidates)

# ------------------------------------------------------- supplier statement


def reconcile_statement(statement: dict, docs: list[dict]) -> pd.DataFrame:
    """Compare a supplier statement's lines with the invoices and credit notes
    received from that supplier. Returns one row per statement line plus any
    received document missing from the statement."""
    supplier = statement.get("counterparty", "")
    ours = [d for d in docs if d["doc_type"] in ("invoice", "credit_note") and d["doc_id"] != statement["doc_id"]
            and name_similarity(d.get("counterparty", ""), supplier) >= 0.8]
    by_ref = {re.sub(r"\s", "", d["document_number"]).upper(): d for d in ours if d["document_number"]}
    rows, seen = [], set()
    for line in statement.get("statement_lines") or []:
        ref = re.sub(r"\s", "", line.get("reference") or "").upper()
        amount = line.get("amount")
        doc = by_ref.get(ref)
        if doc is None:
            status = "Not in our records" if amount and amount > 0 else "Payment / credit on statement"
            rows.append({"Supplier": supplier, "Statement ref": line.get("reference"), "Statement date": line.get("date"),
                         "Statement amount": amount, "Our document": "", "Our amount": None, "Status": status})
            continue
        seen.add(doc["doc_id"])
        ours_amt = -doc["gross_total"] if doc["doc_type"] == "credit_note" and doc["gross_total"] else doc["gross_total"]
        ok = ours_amt is not None and amount is not None and abs(ours_amt - amount) <= 0.01
        rows.append({"Supplier": supplier, "Statement ref": line.get("reference"), "Statement date": line.get("date"),
                     "Statement amount": amount, "Our document": doc["doc_id"], "Our amount": ours_amt,
                     "Status": "Agrees" if ok else "Amount differs"})
    for d in ours:
        if d["doc_id"] not in seen and d["document_number"]:
            rows.append({"Supplier": supplier, "Statement ref": "", "Statement date": None, "Statement amount": None,
                         "Our document": d["doc_id"], "Our amount": d["gross_total"],
                         "Status": "Received, not on statement"})
    return pd.DataFrame(rows)

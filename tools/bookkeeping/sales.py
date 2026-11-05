"""Sales ledger: raise sales invoices from a list of completed work, and the
aged debtor analysis with chase tiers. Deterministic; no AI (Claude only
writes the chase letters, from the facts worked out here)."""

from __future__ import annotations

import re

import pandas as pd

from tools.bookkeeping.checks import Finding
from tools.bookkeeping.matching import name_similarity
from tools.bookkeeping.vat import VAT_CODES, normalise_code

# ----------------------------------------------------------- raise invoices


def _customer(customers: pd.DataFrame | None, name: str) -> dict | None:
    if customers is None or customers.empty:
        return None
    best = max(customers.to_dict("records"), key=lambda c: name_similarity(name, c.get("name", "")), default=None)
    return best if best and name_similarity(name, best.get("name", "")) >= 0.85 else None


def raise_invoices(rows: pd.DataFrame, customers: pd.DataFrame | None, *, invoice_date: pd.Timestamp,
                   first_number: int = 1001, prefix: str = "INV-", default_terms_days: int = 30,
                   default_vat_code: str = "S", group_by: str = "job") -> tuple[pd.DataFrame, list[Finding]]:
    """Group work lines into invoices (one per customer + job/PO) and price them.

    Returns invoice lines (``invoice_number, customer, date, due_date, terms_days,
    po_number, description, quantity, unit_price, net, vat_code, vat, gross,
    status, hold_reason``) and findings.
    """
    findings: list[Finding] = []
    if rows is None or rows.empty:
        return pd.DataFrame(), findings
    df = rows.copy()
    for col in ("job", "po_number", "item", "vat_code"):
        if col not in df:
            df[col] = ""
    key_col = group_by if group_by in df else "customer"
    df["_group"] = df["customer"].astype(str) + "|" + df[key_col].astype(str)
    lines, number = [], first_number
    for _, grp in df.groupby("_group", sort=False):
        cust_name = str(grp["customer"].iloc[0])
        cust = _customer(customers, cust_name)
        inv_no = f"{prefix}{number}"
        number += 1
        terms = int(cust.get("terms_days") or default_terms_days) if cust else default_terms_days
        po = next((p for p in grp["po_number"].astype(str) if p.strip()), "")
        reasons = []
        if customers is not None and not customers.empty and cust is None:
            findings.append(Finding("unknown_customer", subject=cust_name, reference=inv_no, date=invoice_date,
                                    source=str(grp["_source"].iloc[0]) if "_source" in grp else "",
                                    finding=f"{cust_name} is not on the customer list, so terms and address are unknown.",
                                    entry_keys=[f"sales:{inv_no}"]))
            reasons.append("unknown customer")
        if cust and cust.get("po_required") and not po:
            gross_est = 0.0
            for r in grp.to_dict("records"):
                code = normalise_code(r.get("vat_code")) or default_vat_code
                net = round(float(r.get("quantity") or 0) * float(r.get("unit_price") or 0), 2)
                gross_est += net + round(net * VAT_CODES.get(code, 0) / 100, 2)
            job_ref = str(grp[key_col].iloc[0] or inv_no)
            findings.append(Finding("po_missing", subject=cust["name"], reference=job_ref, date=invoice_date,
                                    amount=round(gross_est, 2), source=str(grp["_source"].iloc[0]) if "_source" in grp else "",
                                    finding=f"{cust['name']} needs a purchase order number on every invoice, but the "
                                            f"work for job {grp[key_col].iloc[0] or '(no job ref)'} has none.",
                                    ask=f"Could you send your purchase order number for job {grp[key_col].iloc[0]} "
                                        f"({'; '.join(grp['description'].astype(str).head(2))}) so we can invoice it?",
                                    entry_keys=[f"sales:{inv_no}"]))
            reasons.append("PO missing")
        for r in grp.to_dict("records"):
            qty, price = r.get("quantity"), r.get("unit_price")
            code = normalise_code(r.get("vat_code")) or default_vat_code
            problem = qty is None or price is None or pd.isna(qty) or pd.isna(price) or float(qty) <= 0
            if problem:
                findings.append(Finding("sales_line_problem", subject=cust_name, reference=inv_no, date=invoice_date,
                                        finding=f"Line “{r.get('description')}” has no usable quantity or price.",
                                        entry_keys=[f"sales:{inv_no}"]))
                reasons.append("incomplete line")
                qty, price = 0.0, 0.0
            net = round(float(qty) * float(price), 2)
            vat = round(net * VAT_CODES.get(code, 0) / 100, 2)
            lines.append({"invoice_number": inv_no, "customer": cust["name"] if cust else cust_name,
                          "date": invoice_date, "due_date": invoice_date + pd.Timedelta(days=terms), "terms_days": terms,
                          "po_number": po, "job": r.get("job", ""), "item": r.get("item", "") or "Services",
                          "description": r.get("description", ""), "quantity": float(qty), "unit_price": float(price),
                          "net": net, "vat_code": code, "vat": vat, "gross": round(net + vat, 2),
                          "status": "Held" if reasons else "Ready", "hold_reason": ", ".join(dict.fromkeys(reasons))})
    return pd.DataFrame(lines), findings

# -------------------------------------------------------------- aged debtors


DEFAULT_BUCKETS = [0, 30, 60, 90]  # days overdue: current, 1-30, 31-60, 61-90, 90+
DEFAULT_TIERS = [  # days overdue (from) -> chase tier
    {"from": 1, "tier": "Reminder", "tone": "friendly reminder"},
    {"from": 31, "tier": "Second reminder", "tone": "firm but polite"},
    {"from": 61, "tier": "Final notice", "tone": "final notice before further action"},
]


def bucket_label(days: int, buckets: list[int]) -> str:
    if days <= buckets[0]:
        return "Current"
    for lo, hi in zip(buckets, buckets[1:]):
        if lo < days <= hi:
            return f"{lo + 1}–{hi} days"
    return f"Over {buckets[-1]} days"


def allocate_receipts(invoices: pd.DataFrame, receipts: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply money received (bank lines with positive amounts) to open invoices:
    first by invoice number in the description, then by exact amount for the
    same customer name. Returns (invoices with ``received`` column, receipts with
    ``allocated_to``)."""
    inv = invoices.copy()
    inv["received"] = 0.0
    if receipts is None or receipts.empty:
        return inv, pd.DataFrame(columns=["date", "description", "amount", "allocated_to"])
    rec = receipts[receipts["amount"] > 0].copy()
    rec["allocated_to"] = ""
    outstanding = (inv["amount"] - inv["paid"]).round(2)
    for i, r in rec.iterrows():
        text = f"{r.get('description', '')} {r.get('reference', '')}".upper().replace(" ", "")
        hits = [j for j, num in inv["invoice_number"].items() if num and str(num).upper().replace(" ", "") in text]
        if not hits:
            same = [j for j in inv.index if name_similarity(r.get("description", ""), inv.at[j, "customer"]) >= 0.6
                    and abs(outstanding[j] - inv.at[j, "received"] - r["amount"]) <= 0.01]
            hits = same[:1]
        remaining = float(r["amount"])
        for j in hits:
            take = min(remaining, max(outstanding[j] - inv.at[j, "received"], 0))
            if take <= 0:
                continue
            inv.at[j, "received"] += take
            remaining -= take
        if hits:
            rec.at[i, "allocated_to"] = ", ".join(str(inv.at[j, "invoice_number"]) for j in hits)
        if remaining > 0.01:
            rec.at[i, "allocated_to"] = (rec.at[i, "allocated_to"] + f" (£{remaining:,.2f} unallocated)").strip()
    return inv, rec


def aged_debtors(invoices: pd.DataFrame, *, as_of: pd.Timestamp, customers: pd.DataFrame | None = None,
                 receipts: pd.DataFrame | None = None, buckets: list[int] | None = None,
                 tiers: list[dict] | None = None, dispute_words: str = r"disput|query|queried|on hold|credit requested",
                 default_terms_days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, list[Finding]]:
    """Aged debtor analysis.

    Returns (open items with outstanding balance, days overdue, bucket and chase
    tier; customer summary with one column per bucket; findings).
    """
    buckets = buckets or DEFAULT_BUCKETS
    tiers = sorted(tiers or DEFAULT_TIERS, key=lambda t: t["from"])
    findings: list[Finding] = []
    inv = invoices.copy()
    for col, default in (("paid", 0.0), ("status", ""), ("due_date", pd.NaT), ("invoice_date", pd.NaT), ("project_ref", "")):
        if col not in inv:
            inv[col] = default
    inv["paid"] = inv["paid"].fillna(0.0)
    missing_due = inv["due_date"].isna() & inv["invoice_date"].notna()
    inv.loc[missing_due, "due_date"] = inv.loc[missing_due, "invoice_date"] + pd.Timedelta(days=default_terms_days)
    inv, rec = allocate_receipts(inv, receipts)
    for r in rec[rec["allocated_to"].str.contains("unallocated") | (rec["allocated_to"] == "")].to_dict("records"):
        findings.append(Finding("unallocated_payment", subject=str(r.get("description", "")), date=r.get("date"),
                                amount=float(r["amount"]), source=str(r.get("_source", "")),
                                finding=f"£{r['amount']:,.2f} received on {pd.Timestamp(r['date']):%d %b %Y} "
                                        f"(“{r.get('description', '')}”) could not be matched to an open invoice."))
    inv["outstanding"] = (inv["amount"] - inv["paid"] - inv["received"]).round(2)
    inv["days_overdue"] = (as_of - inv["due_date"]).dt.days.fillna(0).astype(int)
    inv["bucket"] = inv["days_overdue"].map(lambda d: bucket_label(int(d), buckets))
    inv["disputed"] = inv["status"].astype(str).str.contains(dispute_words, case=False, regex=True)

    def tier(days: int) -> str:
        chosen = ""
        for t in tiers:
            if days >= t["from"]:
                chosen = t["tier"]
        return chosen

    inv["chase_tier"] = inv["days_overdue"].map(tier)
    inv.loc[inv["disputed"] | (inv["outstanding"] <= 0.005), "chase_tier"] = ""
    for r in inv[inv["disputed"] & (inv["outstanding"] > 0)].to_dict("records"):
        findings.append(Finding("disputed_invoice", subject=r["customer"], reference=str(r["invoice_number"]),
                                date=r["invoice_date"], amount=r["outstanding"], source=str(r.get("_source", "")),
                                finding=f"Invoice {r['invoice_number']} (£{r['outstanding']:,.2f}) is marked "
                                        f"“{r['status']}”, so it is left out of the chase letter."))
    part = inv[(inv["paid"] + inv["received"] > 0.005) & (inv["outstanding"] > 0.005)]
    for r in part.to_dict("records"):
        findings.append(Finding("part_payment", subject=r["customer"], reference=str(r["invoice_number"]),
                                date=r["invoice_date"], amount=r["outstanding"],
                                finding=f"£{r['paid'] + r['received']:,.2f} paid against £{r['amount']:,.2f}; "
                                        f"£{r['outstanding']:,.2f} still due."))
    # customer summary
    labels = ["Current"] + [f"{lo + 1}–{hi} days" for lo, hi in zip(buckets, buckets[1:])] + [f"Over {buckets[-1]} days"]
    summary = inv.pivot_table(index="customer", columns="bucket", values="outstanding", aggfunc="sum", fill_value=0.0)
    summary = summary.reindex(columns=labels, fill_value=0.0)
    summary["Total outstanding"] = summary.sum(axis=1)
    summary = summary.reset_index().rename(columns={"customer": "Customer"})
    summary = summary.sort_values("Total outstanding", ascending=False).reset_index(drop=True)
    cust_lookup = {c.get("name"): c for c in (customers.to_dict("records") if customers is not None and not customers.empty else [])}
    for r in summary.to_dict("records"):
        name = r["Customer"]
        cust = cust_lookup.get(name) or {}
        if r["Total outstanding"] < -0.005:
            findings.append(Finding("credit_balance", subject=name, amount=r["Total outstanding"],
                                    finding=f"{name} has a credit balance of £{-r['Total outstanding']:,.2f}."))
        limit = cust.get("credit_limit")
        if limit and not pd.isna(limit) and r["Total outstanding"] > float(limit):
            findings.append(Finding("over_credit_limit", subject=name, amount=r["Total outstanding"],
                                    finding=f"£{r['Total outstanding']:,.2f} owed against a credit limit of £{float(limit):,.0f}."))
        chase = inv[(inv["customer"] == name) & (inv["chase_tier"] != "")]
        if not chase.empty and cust_lookup and not cust.get("email"):
            findings.append(Finding("no_contact", subject=name, finding=f"{name} has overdue invoices but no accounts email on file."))
        final = chase[chase["chase_tier"] == tiers[-1]["tier"]]
        if not final.empty:
            findings.append(Finding("final_notice", subject=name, amount=round(float(final["outstanding"].sum()), 2),
                                    reference=", ".join(final["invoice_number"].astype(str)),
                                    finding=f"{len(final)} invoice(s) totalling £{final['outstanding'].sum():,.2f} are more "
                                            f"than {tiers[-1]['from'] - 1} days overdue; a final notice has been drafted."))
    return inv, summary, findings


def chase_groups(open_items: pd.DataFrame, customers: pd.DataFrame | None, tiers: list[dict] | None = None) -> list[dict]:
    """One chase letter per customer with something to chase, at the most serious tier."""
    tiers = sorted(tiers or DEFAULT_TIERS, key=lambda t: t["from"])
    rank = {t["tier"]: i for i, t in enumerate(tiers)}
    tone = {t["tier"]: t.get("tone", "") for t in tiers}
    cust_lookup = {c.get("name"): c for c in (customers.to_dict("records") if customers is not None and not customers.empty else [])}
    out = []
    for name, grp in open_items[open_items["chase_tier"] != ""].groupby("customer", sort=True):
        top = max(grp["chase_tier"], key=lambda t: rank.get(t, 0))
        cust = cust_lookup.get(name, {})
        out.append({
            "customer": name, "contact": cust.get("contact", ""), "email": cust.get("email", ""), "tier": top,
            "tone": tone.get(top, ""), "total_overdue": round(float(grp["outstanding"].sum()), 2),
            "invoices": [{"invoice": str(r["invoice_number"]), "date": f"{r['invoice_date']:%d %b %Y}" if pd.notna(r["invoice_date"]) else "",
                          "due": f"{r['due_date']:%d %b %Y}" if pd.notna(r["due_date"]) else "",
                          "outstanding": round(float(r["outstanding"]), 2), "days_overdue": int(r["days_overdue"]),
                          **({"project": r["project_ref"]} if str(r.get("project_ref", "")).strip() else {})}
                         for r in grp.sort_values("due_date").to_dict("records")],
        })
    return out


def invoice_number_key(value: str) -> str:
    return re.sub(r"\s", "", str(value or "")).upper()

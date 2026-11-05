"""Purchase orders: match supplier invoices to POs (by PO number first, then
supplier and amount) and flag invoices with no PO, unknown POs and
over-billing. Deterministic; no AI."""

from __future__ import annotations

import re

import pandas as pd

from tools.bookkeeping.checks import Finding
from tools.bookkeeping.matching import name_similarity


def _key(po: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(po or "").upper())


def match_invoices_to_pos(docs: list[dict], pos: pd.DataFrame, *, tolerance_pct: float = 2.0,
                          tolerance_abs: float = 5.0, require_po: bool = True) -> tuple[pd.DataFrame, list[Finding]]:
    """Returns (reconciliation table, findings). Credit notes are ignored."""
    findings: list[Finding] = []
    rows = []
    pos = pos.copy() if pos is not None else pd.DataFrame(columns=["po_number", "supplier", "net_amount"])
    pos["_key"] = pos["po_number"].map(_key)
    invoiced: dict[str, float] = {}
    by_key = {k: r for k, r in zip(pos["_key"], pos.to_dict("records"))}
    for d in [d for d in docs if d["doc_type"] == "invoice"]:
        key = _key(d.get("po_number"))
        net = d.get("net_total") or 0.0
        po = by_key.get(key) if key else None
        how = "PO number"
        if po is None and not key:  # try supplier + amount
            same = [r for r in pos.to_dict("records") if name_similarity(r.get("supplier", ""), d["counterparty"]) >= 0.8
                    and abs((r.get("net_amount") or 0) - net) <= max(tolerance_abs, net * tolerance_pct / 100)]
            po, how = (same[0], "supplier and amount") if len(same) == 1 else (None, "")
        base = {"Doc": d["doc_id"], "Supplier": d["counterparty"], "Invoice": d["document_number"],
                "Invoice date": d["document_date"], "Invoice net": net, "PO on invoice": d.get("po_number", "")}
        if po is None:
            check = "po_not_found" if key else "invoice_without_po"
            if check == "invoice_without_po" and not require_po:
                continue
            msg = (f"PO {d['po_number']} on the invoice is not on the PO list." if key
                   else "The invoice quotes no purchase order and none matches by supplier and amount.")
            findings.append(Finding(check, subject=d["counterparty"], reference=d["document_number"],
                                    date=d["document_date"], amount=d.get("gross_total"), source=d["file"],
                                    doc_ids=[d["doc_id"]], finding=msg,
                                    ask=(f"Your invoice {d['document_number']} quotes PO {d['po_number']}, which we can't "
                                         f"find. Could you check the order number?") if key else
                                        f"Your invoice {d['document_number']} has no purchase order number. Which order is it for?"))
            rows.append({**base, "Matched PO": "", "Matched by": "", "PO net": None, "Invoiced to date": None,
                         "Difference": None, "Status": "No PO" if not key else "PO not found"})
            continue
        po_key = po["_key"]
        invoiced[po_key] = round(invoiced.get(po_key, 0.0) + net, 2)
        po_net = float(po.get("net_amount") or 0)
        over = round(invoiced[po_key] - po_net, 2)
        status = "Matched"
        if name_similarity(po.get("supplier", ""), d["counterparty"]) < 0.8:
            status = "Supplier differs"
            findings.append(Finding("po_supplier_mismatch", subject=d["counterparty"], reference=d["document_number"],
                                    date=d["document_date"], amount=d.get("gross_total"), source=d["file"],
                                    doc_ids=[d["doc_id"]],
                                    finding=f"PO {po['po_number']} was raised with {po.get('supplier')}, not {d['counterparty']}."))
        elif over > max(tolerance_abs, po_net * tolerance_pct / 100):
            status = "Over PO value"
            findings.append(Finding("po_overbilled", subject=d["counterparty"], reference=d["document_number"],
                                    date=d["document_date"], amount=over, source=d["file"], doc_ids=[d["doc_id"]],
                                    finding=f"Invoiced £{invoiced[po_key]:,.2f} net against PO {po['po_number']} for "
                                            f"£{po_net:,.2f} (over by £{over:,.2f}).",
                                    ask=f"Invoice {d['document_number']} takes PO {po['po_number']} £{over:,.2f} over the "
                                        f"agreed £{po_net:,.2f}. Could you explain the extra or send a corrected invoice?"))
        rows.append({**base, "Matched PO": po["po_number"], "Matched by": how, "PO net": po_net,
                     "Invoiced to date": invoiced[po_key], "Difference": over, "Status": status})
    table = pd.DataFrame(rows)
    open_pos = pos[~pos["_key"].isin(invoiced)].drop(columns=["_key"])
    if not open_pos.empty:
        extra = pd.DataFrame([{"Doc": "", "Supplier": r.get("supplier"), "Invoice": "", "Invoice date": None,
                               "Invoice net": None, "PO on invoice": "", "Matched PO": r.get("po_number"),
                               "Matched by": "", "PO net": r.get("net_amount"), "Invoiced to date": 0.0,
                               "Difference": None, "Status": "Awaiting invoice"} for r in open_pos.to_dict("records")])
        table = pd.concat([table, extra], ignore_index=True) if not table.empty else extra
    return table, findings

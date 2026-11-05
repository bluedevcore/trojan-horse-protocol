"""Month-end checklist: config lists the items; automatic items get their
status from this run, manual items stay "To do" for a person.

Config (``month_end.checklist``), in display order:
    - {id: purchase_invoices}                    automatic item, default label
    - {id: card_matched, label: "Card spend matched to receipts"}
    - {label: "Reconcile the bank in QuickBooks", manual: true}
Automatic ids: purchase_invoices, duplicates, bank_details, vat_checks, supplier_queries,
card_matched, missing_receipts, coding_review, prepayments_accruals, payroll_journal,
sales_invoices, debtors_chased, timesheets_approved, po_matched, statements_reconciled,
documents_filed, vat_return.
"""

from __future__ import annotations

import pandas as pd

DONE, ACTION, TODO = "Done", "Action needed", "To do"


def _ids(by_check: dict, *checks: str) -> list[str]:
    out = []
    for c in checks:
        out += by_check.get(c, [])
    return sorted(set(out))


def _item(label, status, detail, ids=()):
    return {"Item": label, "Status": status, "Detail": detail, "Exceptions": ", ".join(ids)}


def _purchase_invoices(f, b):
    if not f.get("purchase_docs"):
        return None
    ids = _ids(b, "arithmetic", "missing_fields", "vat_without_number", "vat_number_invalid", "bank_details_changed",
               "possible_duplicate", "invoice_without_po", "po_not_found", "po_overbilled")
    held = f.get("purchase_held", 0)
    detail = f"{f['purchase_ready']} of {f['purchase_docs']} supplier documents coded and in the import file"
    detail += f"; {held} held for a check" if held else ""
    return ("Supplier invoices and credit notes processed", ACTION if held else DONE, detail, ids)


def _duplicates(f, b):
    if not f.get("purchase_docs"):
        return None
    ids = _ids(b, "duplicate_document", "possible_duplicate")
    return ("Duplicate invoices removed", DONE if not _ids(b, "possible_duplicate") else ACTION,
            f"{len(ids)} duplicate(s) found and kept out of the import" if ids else "No duplicates found", ids)


def _bank_details(f, b):
    if not f.get("purchase_docs"):
        return None
    ids = _ids(b, "bank_details_changed")
    return ("Supplier bank detail changes verified", ACTION if ids else DONE,
            f"{len(ids)} change(s) to verify by phone before the payment run" if ids else "No changes to bank details", ids)


def _vat_checks(f, b):
    if not f.get("purchase_docs") and not f.get("card_txns"):
        return None
    ids = _ids(b, "vat_rate", "vat_without_number", "vat_number_invalid", "vat_number_mismatch", "foreign_currency")
    return ("VAT checked on purchases", ACTION if ids else DONE,
            f"{len(ids)} VAT point(s) to resolve before the VAT return" if ids else "Rates, numbers and arithmetic checked", ids)


def _supplier_queries(f, b):
    n = f.get("letters_by_type", {}).get("supplier", 0)
    if not f.get("purchase_docs"):
        return None
    return ("Supplier queries raised", ACTION if n else DONE,
            f"{n} query email(s) drafted, ready to check and send" if n else "No supplier queries needed", [])


def _card_matched(f, b):
    if not f.get("card_txns"):
        return None
    unmatched = f["card_txns"] - f["card_matched"] - f.get("card_no_receipt_needed", 0)
    ids = _ids(b, "missing_receipt", "amount_mismatch", "receipt_unmatched")
    return ("Card transactions matched to receipts", ACTION if ids else DONE,
            f"{f['card_matched']} of {f['card_txns']} matched; {max(unmatched, 0)} without a receipt", ids)


def _missing_receipts(f, b):
    if not f.get("card_txns"):
        return None
    ids = _ids(b, "missing_receipt")
    n = f.get("letters_by_type", {}).get("cardholder", 0)
    return ("Missing receipts requested", ACTION if ids else DONE,
            f"{len(ids)} receipt(s) missing; {n} request email(s) drafted" if ids else "Every card payment has a receipt", ids)


def _coding_review(f, b):
    if not f.get("entries"):
        return None
    ids = _ids(b, "low_confidence_coding")
    return ("Nominal coding reviewed", ACTION if ids else DONE,
            f"{len(ids)} AI coding suggestion(s) need a decision" if ids else "All entries coded with confidence", ids)


def _prepayments(f, b):
    ids = _ids(b, "prepayment", "prior_period", "future_dated")
    if not f.get("purchase_docs"):
        return None
    return ("Prepayments and accruals reviewed", ACTION if ids else DONE,
            f"{len(_ids(b, 'prepayment'))} prepayment(s) to spread; {len(_ids(b, 'prior_period', 'future_dated'))} "
            f"invoice(s) dated outside the month" if ids else "Nothing to adjust", ids)


def _payroll(f, b):
    if not f.get("payroll_employees"):
        return None
    ids = _ids(b, "payroll_net_mismatch", "payroll_total_mismatch", "payroll_journal_unbalanced")
    diff = f.get("payroll_difference", 0)
    detail = f"Journal for {f['payroll_employees']} employees, gross £{f['payroll_gross']:,.2f}"
    detail += f"; £{abs(diff):,.2f} in Suspense until the payslip query is answered" if abs(diff) > 0.005 else ", balanced"
    return ("Payroll journal prepared", ACTION if ids else DONE, detail, ids)


def _sales(f, b):
    if not f.get("sales_invoices"):
        return None
    ids = _ids(b, "po_missing", "unknown_customer", "sales_line_problem")
    return ("Sales invoices raised", ACTION if f.get("sales_held") else DONE,
            f"{f['sales_ready']} of {f['sales_invoices']} invoices ready to import"
            + (f"; {f['sales_held']} held" if f.get("sales_held") else ""), ids)


def _debtors(f, b):
    if not f.get("debtor_items"):
        return None
    ids = _ids(b, "disputed_invoice", "unallocated_payment", "credit_balance", "final_notice", "no_contact")
    n = f.get("letters_by_type", {}).get("customer", 0)
    return ("Overdue accounts chased", ACTION if n or ids else DONE,
            f"£{f.get('debtors_overdue', 0):,.2f} overdue; {n} chase letter(s) drafted for approval", ids)


def _timesheets(f, b):
    if not f.get("timesheet_rows"):
        return None
    ids = _ids(b, "unknown_employee", "excess_hours", "missing_approval", "duplicate_timesheet", "hours_mismatch",
               "missing_timesheet", "overlapping_shifts", "unknown_job", "closed_job")
    held = len(f.get("hours_held", []))
    return ("Timesheets checked and approved", ACTION if ids else DONE,
            f"{f['timesheet_rows']} timesheet lines for {f.get('timesheet_employees', 0)} employees"
            + (f"; {held} employee-week{'s' if held != 1 else ''} held from the payroll file" if held else ""), ids)


def _po(f, b):
    if not f.get("po_lines"):
        return None
    ids = _ids(b, "invoice_without_po", "po_not_found", "po_overbilled", "po_supplier_mismatch")
    return ("Invoices matched to purchase orders", ACTION if ids else DONE,
            f"{f.get('po_matched', 0)} invoice(s) matched to a PO", ids)


def _statements(f, b):
    if not f.get("statements"):
        return None
    ids = _ids(b, "statement_missing_invoice", "statement_amount_mismatch")
    return ("Supplier statements reconciled", ACTION if ids else DONE, f"{f['statements']} statement(s) checked", ids)


def _filing(f, b):
    if not f.get("filing_docs"):
        return None
    ids = _ids(b, "unfiled_document")
    return ("Documents filed to project folders", ACTION if ids else DONE,
            f"{f['filing_docs'] - len(ids)} of {f['filing_docs']} filed", ids)


def _vat_return(f, b):
    if not f.get("vat_return"):
        return None
    return ("VAT return workings prepared", ACTION, f"Box 5 £{f['vat_return_box5']:,.2f} (draft for review)", [])


EVALUATORS = {
    "purchase_invoices": _purchase_invoices, "duplicates": _duplicates, "bank_details": _bank_details,
    "vat_checks": _vat_checks, "supplier_queries": _supplier_queries, "card_matched": _card_matched,
    "missing_receipts": _missing_receipts, "coding_review": _coding_review, "prepayments_accruals": _prepayments,
    "payroll_journal": _payroll, "sales_invoices": _sales, "debtors_chased": _debtors,
    "timesheets_approved": _timesheets, "po_matched": _po, "statements_reconciled": _statements,
    "documents_filed": _filing, "vat_return": _vat_return,
}


def checklist(config: dict, facts: dict, by_check: dict[str, list[str]]) -> pd.DataFrame:
    items = (config.get("month_end") or {}).get("checklist") or [{"id": k} for k in EVALUATORS]
    rows = []
    for item in items:
        if item.get("manual") or not item.get("id"):
            rows.append(_item(item.get("label", ""), TODO, item.get("detail", "Manual step for the accounts team")))
            continue
        fn = EVALUATORS.get(item["id"])
        res = fn(facts, by_check) if fn else None
        if res is None:
            continue
        label, status, detail, ids = res
        rows.append(_item(item.get("label") or label, status, detail, ids))
    return pd.DataFrame(rows, columns=["Item", "Status", "Detail", "Exceptions"])

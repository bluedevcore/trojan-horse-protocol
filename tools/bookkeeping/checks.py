"""Findings (exceptions) raised by the bookkeeping checks.

Each check has defaults below. A client config can override any of them
under ``checks.<check_id>`` (``label``, ``severity``, ``needs_human_check``,
``hold``, ``enabled``), e.g. to make a missing receipt a human check.

``hold`` means the entries behind the finding are kept out of the
accounting-system import files until a person clears it.
``letter`` names who gets a drafted email about it (supplier, cardholder,
customer, payroll_bureau); findings with the same recipient share one email.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
BUILT_IN_RECIPIENTS = ("supplier", "cardholder", "customer", "payroll_bureau")
AREA_ORDER = ["Purchases", "VAT", "Card", "Payroll", "Sales", "Debtors", "Timesheets", "Orders", "Statements",
              "Filing", "Documents"]

# check id: label, area, severity, needs_human_check, hold, letter recipient type, suggested action
CHECKS: dict[str, dict] = {
    # documents / purchases
    "unreadable_document": dict(label="Document could not be read", area="Documents", severity="Medium", human=True,
                                hold=False, action="Open the file and key it in by hand, or upload a clearer copy."),
    "missing_fields": dict(label="Key details missing", area="Purchases", severity="Medium", human=True, hold=True,
                           action="Check the document and fill in the missing details before posting."),
    "low_confidence_extraction": dict(label="Document hard to read", area="Documents", severity="Medium", human=True,
                                      hold=False, action="Compare the extracted fields with the document."),
    "arithmetic": dict(label="Totals don't add up", area="Purchases", severity="High", human=True, hold=True,
                       letter="supplier", action="Ask the supplier for a corrected invoice; do not post until it arrives."),
    "vat_rate": dict(label="Unusual VAT rate", area="VAT", severity="Medium", human=True, hold=False,
                     letter="supplier", action="Check the VAT rate with the supplier before reclaiming the VAT."),
    "duplicate_document": dict(label="Duplicate invoice", area="Purchases", severity="Medium", human=False, hold=True,
                               action="Second copy not posted. No action unless the supplier says it is a separate invoice."),
    "possible_duplicate": dict(label="Possible duplicate", area="Purchases", severity="Medium", human=True, hold=True,
                               action="Compare the two documents; post only one if they are the same charge."),
    "bank_details_changed": dict(label="Supplier bank details changed", area="Purchases", severity="High", human=True,
                                 hold=True, letter="supplier",
                                 action="Phone the supplier on the number already on file (not one on the invoice or email) "
                                        "to confirm before paying or updating the bank details."),
    "vat_without_number": dict(label="VAT charged without a VAT number", area="VAT", severity="Medium", human=True,
                               hold=True, letter="supplier",
                               action="Ask the supplier for a valid VAT invoice showing their VAT number, or a corrected "
                                      "invoice without VAT."),
    "vat_number_invalid": dict(label="VAT number fails HMRC check", area="VAT", severity="High", human=True, hold=True,
                               letter="supplier",
                               action="Check the number on HMRC's VAT number checker and ask the supplier to confirm it."),
    "vat_number_mismatch": dict(label="VAT number differs from records", area="VAT", severity="Medium", human=True,
                                hold=False, action="Check which VAT number is right and update the supplier record."),
    "new_supplier": dict(label="New supplier", area="Purchases", severity="Medium", human=True, hold=False,
                         action="Set the supplier up in the accounts system after checking their details."),
    "prior_period": dict(label="Dated before this period", area="Purchases", severity="Medium", human=True, hold=False,
                         action="Check it isn't already posted. If the earlier month is closed, post it in this "
                                "month or accrue it."),
    "future_dated": dict(label="Dated after this period", area="Purchases", severity="Low", human=True, hold=True,
                         action="Hold for next month unless the goods or services were received this month."),
    "prepayment": dict(label="Prepayment to spread", area="Purchases", severity="Low", human=False, hold=False,
                       action="Post to prepayments and release one month at a time (month-end journal)."),
    "foreign_currency": dict(label="Overseas supplier: reverse charge", area="VAT", severity="Medium", human=True,
                             hold=False, action="Account for reverse-charge VAT on the overseas service."),
    "low_confidence_coding": dict(label="Coding needs a decision", area="Purchases", severity="Medium", human=True,
                                  hold=False, action="Choose the right account; the suggestion is only a guess."),
    "blocked_vat": dict(label="VAT not reclaimable", area="VAT", severity="Low", human=False, hold=False,
                        action="Posted gross with no VAT reclaimed."),
    "statement_missing_invoice": dict(label="On supplier statement, not in our records", area="Statements",
                                      severity="Medium", human=True, hold=False, letter="supplier",
                                      action="Ask the supplier for a copy of the invoice."),
    "statement_amount_mismatch": dict(label="Statement amount differs", area="Statements", severity="Medium",
                                      human=True, hold=False, letter="supplier",
                                      action="Agree the correct amount with the supplier."),
    # card / bank
    "missing_receipt": dict(label="Missing receipt", area="Card", severity="Medium", human=False, hold=False,
                            letter="cardholder", action="Ask the cardholder for the receipt (email drafted)."),
    "amount_mismatch": dict(label="Receipt and card amounts differ", area="Card", severity="Low", human=True, hold=False,
                            action="Check the difference (often a tip or a part-refund) before posting."),
    "receipt_unmatched": dict(label="Receipt with no card transaction", area="Card", severity="Medium", human=True,
                              hold=True, action="Check how it was paid; if paid personally, process it as an expense claim."),
    # payroll
    "payroll_net_mismatch": dict(label="Net pay doesn't reconcile", area="Payroll", severity="High", human=True,
                                 hold=False, letter="payroll_bureau",
                                 action="Ask the payroll bureau to confirm the payslip before wages are paid."),
    "payroll_total_mismatch": dict(label="Payroll report total differs", area="Payroll", severity="Medium", human=True,
                                   hold=False, letter="payroll_bureau",
                                   action="Ask the payroll bureau which figure is right."),
    "payroll_journal_unbalanced": dict(label="Payroll journal out of balance", area="Payroll", severity="High",
                                       human=False, hold=False,
                                       action="Difference posted to Suspense; clear it when the payslip is confirmed."),
    # sales
    "po_missing": dict(label="Customer PO missing", area="Sales", severity="Medium", human=True, hold=True,
                       letter="customer", action="Ask the customer for their purchase order number, then raise the invoice."),
    "unknown_customer": dict(label="Customer not on file", area="Sales", severity="Medium", human=True, hold=True,
                             action="Set the customer up (address, terms) before invoicing."),
    "sales_line_problem": dict(label="Sales line incomplete", area="Sales", severity="Medium", human=True, hold=True,
                               action="Complete the quantity, price and VAT code."),
    "over_credit_limit": dict(label="Over credit limit", area="Sales", severity="Medium", human=True, hold=False,
                              action="Ask the credit controller whether to continue supplying."),
    # debtors
    "disputed_invoice": dict(label="Disputed invoice", area="Debtors", severity="Medium", human=True, hold=False,
                             action="Resolve the query before chasing; it is left out of the chase letter."),
    "credit_balance": dict(label="Customer in credit", area="Debtors", severity="Low", human=True, hold=False,
                           action="Check for an overpayment or unallocated credit; refund or allocate it."),
    "unallocated_payment": dict(label="Payment not matched to an invoice", area="Debtors", severity="Medium",
                                human=True, hold=False, action="Find which invoice(s) the payment is for and allocate it."),
    "part_payment": dict(label="Part payment", area="Debtors", severity="Low", human=False, hold=False,
                         action="Balance included in the chase letter."),
    "no_contact": dict(label="No contact email", area="Debtors", severity="Low", human=True, hold=False,
                       action="Add an accounts email address for this customer."),
    "final_notice": dict(label="Seriously overdue", area="Debtors", severity="High", human=True, hold=False,
                         letter="customer", action="Approve the final notice before it is sent; consider stopping supply."),
    # timesheets
    "unknown_employee": dict(label="Employee not on the list", area="Timesheets", severity="Medium", human=True,
                             hold=True, action="Check the name or add the employee before payroll."),
    "excess_hours": dict(label="Unusually long day", area="Timesheets", severity="Medium", human=True, hold=False,
                         action="Check the times with the supervisor."),
    "missing_approval": dict(label="Timesheet not approved", area="Timesheets", severity="Medium", human=True,
                             hold=True, action="Get the supervisor's approval before payroll."),
    "duplicate_timesheet": dict(label="Duplicate timesheet entry", area="Timesheets", severity="Medium", human=True,
                                hold=True, action="Remove the duplicate entry."),
    "hours_mismatch": dict(label="Hours don't match start/finish", area="Timesheets", severity="Medium", human=True,
                           hold=False, action="Check which figure is right."),
    "missing_timesheet": dict(label="No timesheet", area="Timesheets", severity="Medium", human=True, hold=False,
                              action="Chase the missing timesheet before the payroll cut-off."),
    "overlapping_shifts": dict(label="Overlapping timesheet lines", area="Timesheets", severity="Medium", human=True,
                               hold=True, action="Check the times with the supervisor; the overlap must not be paid twice."),
    "unknown_job": dict(label="Job not on the job list", area="Timesheets", severity="Medium", human=True, hold=False,
                        action="Find the right job number so the labour cost goes to the right job."),
    "closed_job": dict(label="Hours on a closed job", area="Timesheets", severity="Medium", human=True, hold=False,
                       action="Check whether the job was reopened (e.g. snagging) or the hours belong to another job."),
    # purchase orders
    "invoice_without_po": dict(label="Invoice without a PO", area="Orders", severity="Medium", human=True, hold=True,
                               letter="supplier", action="Find the PO or get the spend approved before posting."),
    "po_not_found": dict(label="PO number not recognised", area="Orders", severity="Medium", human=True, hold=True,
                         letter="supplier", action="Check the PO number with the supplier."),
    "po_overbilled": dict(label="Invoice exceeds the PO", area="Orders", severity="High", human=True, hold=True,
                          letter="supplier", action="Get the extra cost approved, or ask the supplier for a corrected invoice."),
    "po_supplier_mismatch": dict(label="PO raised with a different supplier", area="Orders", severity="Medium",
                                 human=True, hold=True, action="Check the PO and the supplier."),
    # filing
    "unfiled_document": dict(label="Could not tell which project", area="Filing", severity="Low", human=True,
                             hold=False, action="Choose the project folder for this document."),
}


@dataclass
class Finding:
    check_id: str
    subject: str  # supplier / cardholder / customer / employee
    finding: str  # deterministic plain-English description
    reference: str = ""
    date: pd.Timestamp | None = None
    amount: float | None = None
    source: str = ""
    doc_ids: list[str] = field(default_factory=list)
    txn_ids: list[str] = field(default_factory=list)
    entry_keys: list[str] = field(default_factory=list)  # which entries to hold
    contact: str = ""  # letter recipient name (defaults to subject)
    ref_text: str = ""  # how the item is referred to in a letter (default built from reference/date/amount)
    ask: str = ""  # one-line request for the letter
    action: str = ""  # overrides the default suggested action
    severity: str = ""  # overrides the default severity
    # filled from the registry/config
    label: str = ""
    area: str = ""
    needs_human_check: bool = False
    hold: bool = False
    letter: str = ""
    id: str = ""


def configure(f: Finding, config: dict) -> Finding | None:
    """Apply registry defaults and client overrides; None if the check is switched off."""
    base = dict(CHECKS.get(f.check_id, {}))
    base.update((config.get("checks") or {}).get(f.check_id) or {})
    if base.get("enabled") is False:
        return None
    f.label = base.get("label", f.check_id)
    f.area = base.get("area", "Purchases")
    f.severity = str(base.get("severity", "Medium")).capitalize() if not f.severity else f.severity
    f.needs_human_check = bool(base.get("needs_human_check", base.get("human", False)))
    f.hold = bool(base.get("hold", False))
    f.letter = base.get("letter", "") or ""
    f.action = f.action or base.get("action", "")
    fixed = (config.get("contacts") or {}).get(f.letter)
    if f.letter not in BUILT_IN_RECIPIENTS and isinstance(fixed, dict) and fixed.get("name"):
        f.contact = fixed["name"]  # e.g. timesheet queries go to one site manager, not to the employee
    f.contact = f.contact or f.subject
    return f


def finalise(findings: list[Finding], config: dict) -> list[Finding]:
    """Configure, sort (area, severity, date) and number EX-01, EX-02, ..."""
    out = [f for f in (configure(x, config) for x in findings) if f is not None]
    area_rank = {a: i for i, a in enumerate(AREA_ORDER)}
    out.sort(key=lambda f: (area_rank.get(f.area, 99), SEVERITY_ORDER.get(f.severity, 3),
                            f.date if f.date is not None else pd.Timestamp.max, f.subject, f.reference))
    for i, f in enumerate(out, 1):
        f.id = f"EX-{i:02d}"
    return out


def findings_frame(findings: list[Finding]) -> pd.DataFrame:
    cols = ["ID", "Severity", "Area", "Check", "Who", "Reference", "Date", "Amount", "Finding", "Suggested action",
            "Needs human check", "Held from import", "Email drafted to", "Source"]
    rows = [{
        "ID": f.id, "Severity": f.severity, "Area": f.area, "Check": f.label, "Who": f.subject,
        "Reference": f.reference, "Date": f.date, "Amount": f.amount, "Finding": f.finding,
        "Suggested action": f.action, "Needs human check": "Yes" if f.needs_human_check else "No",
        "Held from import": "Yes" if f.hold else "No", "Email drafted to": f.contact if f.letter else "",
        "Source": f.source,
    } for f in findings]
    return pd.DataFrame(rows, columns=cols)

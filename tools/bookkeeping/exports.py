"""Import files for QuickBooks Online, Xero and Sage 50, as plain CSVs.

Every export is built from the same coded entries; only entries with status
"Ready" are included (held entries wait for a human check). Column layouts
follow each system's CSV import templates; check the mapping screen on the
first import, as the systems change their templates from time to time.

Config keys (all optional):
    accounting_system: quickbooks | xero | sage50
    exports: [list of export keys]            default: every export for the system
    export_settings:
        card_payment_account: Company credit card  (QuickBooks / Xero name)
        tracking_as_class: false                   QuickBooks: put the tracking value (property/project) in Class
        tracking_name: Property                    Xero: tracking category name for the tracking value
        card_bank_nominal: "1240"                  (Sage nominal for the card)
        journal_number: PAYROLL-OCT-26
        tax_codes: {S: "20.0% S", ...}             override the VAT code mapping
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TAX_CODES = {
    "quickbooks": {"S": "20.0% S", "R": "5.0% R", "Z": "0.0% Z", "E": "Exempt", "O": "No VAT", "RC": "20.0% RC"},
    "xero": {"S": "20% (VAT on Expenses)", "R": "5% (VAT on Expenses)", "Z": "Zero Rated Expenses",
             "E": "Exempt Expenses", "O": "No VAT", "RC": "Reverse Charge Expenses (20%)"},
    "xero_sales": {"S": "20% (VAT on Income)", "R": "5% (VAT on Income)", "Z": "Zero Rated Income",
                   "E": "Exempt Income", "O": "No VAT", "RC": "No VAT"},
    "sage50": {"S": "T1", "R": "T5", "Z": "T0", "E": "T2", "O": "T9", "RC": "T22"},
}
SYSTEM_LABELS = {"quickbooks": "QuickBooks Online", "xero": "Xero", "sage50": "Sage 50"}


@dataclass
class ExportFile:
    key: str
    label: str
    file_name: str
    frame: pd.DataFrame
    help: str = ""


def _d(value) -> str:
    return "" if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%d/%m/%Y")


def _ready(entries: pd.DataFrame, kind: str) -> pd.DataFrame:
    if entries is None or entries.empty:
        return pd.DataFrame()
    return entries[(entries["kind"] == kind) & (entries["status"] == "Ready")]


def _tax(system: str, settings: dict, code: str, sales: bool = False) -> str:
    table = dict(TAX_CODES["xero_sales" if sales and system == "xero" else system])
    table.update((settings.get("tax_codes") or {}))
    return table.get(code, table.get("O", ""))


def _amount(v) -> float:
    return round(float(v), 2)

# ------------------------------------------------------------- QuickBooks


def qb_bills(entries, settings, **_):
    e = _ready(entries, "bill")
    return pd.DataFrame([{
        "Bill No": r["reference"], "Supplier": r["counterparty"], "Bill Date": _d(r["date"]), "Due Date": _d(r["due_date"]),
        "Terms": f"Net {int(r['terms_days'])}" if pd.notna(r.get("terms_days")) and r.get("terms_days") else "",
        "Memo": r.get("memo", ""), "Account": r["account"], "Line Description": r["description"],
        "Line Amount": _amount(r["net"]), "Line Tax Code": _tax("quickbooks", settings, r["vat_code"]),
        "Line Tax Amount": _amount(r["vat"])} for r in e.to_dict("records")])


def qb_supplier_credits(entries, settings, **_):
    e = _ready(entries, "supplier_credit")
    return pd.DataFrame([{
        "Ref No": r["reference"], "Supplier": r["counterparty"], "Date": _d(r["date"]), "Memo": r.get("memo", ""),
        "Account": r["account"], "Line Description": r["description"], "Line Amount": _amount(r["net"]),
        "Line Tax Code": _tax("quickbooks", settings, r["vat_code"]), "Line Tax Amount": _amount(r["vat"])}
        for r in e.to_dict("records")])


def qb_expenses(entries, settings, **_):
    e = _ready(entries, "card_expense")
    return pd.DataFrame([{
        "Date": _d(r["date"]), "Ref No": r["reference"], "Payee": r["counterparty"],
        "Payment Account": settings.get("card_payment_account", "Company credit card"), "Payment Method": "Credit card",
        "Memo": r.get("memo", ""), "Account": r["account"], "Line Description": r["description"],
        "Line Amount": _amount(r["net"]), "Line Tax Code": _tax("quickbooks", settings, r["vat_code"]),
        "Line Tax Amount": _amount(r["vat"]),
        "Class": r.get("tracking", "") if settings.get("tracking_as_class") else ""} for r in e.to_dict("records")])


def qb_journal(entries, settings, journal=None, **_):
    if journal is None or journal.empty:
        return pd.DataFrame()
    number = settings.get("journal_number") or str(journal["reference"].iloc[0])
    return pd.DataFrame([{
        "Journal No": number, "Journal Date": _d(r["date"]), "Account": r["account"],
        "Debits": _amount(r["debit"]) if r["debit"] else "", "Credits": _amount(r["credit"]) if r["credit"] else "",
        "Description": r["description"], "Name": "", "Class": r.get("class", "")} for r in journal.to_dict("records")])


def qb_invoices(entries, settings, sales=None, **_):
    s = sales[sales["status"] == "Ready"] if sales is not None and not sales.empty else pd.DataFrame()
    return pd.DataFrame([{
        "Invoice No": r["invoice_number"], "Customer": r["customer"], "Invoice Date": _d(r["date"]),
        "Due Date": _d(r["due_date"]), "Terms": f"Net {int(r['terms_days'])}", "Memo": f"PO {r['po_number']}" if r["po_number"] else "",
        "Product/Service": r["item"], "Description": r["description"], "Qty": r["quantity"], "Rate": r["unit_price"],
        "Amount": _amount(r["net"]), "Tax Code": _tax("quickbooks", settings, r["vat_code"]),
        "Tax Amount": _amount(r["vat"])} for r in s.to_dict("records")])

# ------------------------------------------------------------------- Xero


def _xero_lines(rows, settings, sales=False, sign=1):
    return [{
        "*ContactName": r["counterparty"], "EmailAddress": "", "*InvoiceNumber": r["reference"],
        "Reference": r.get("memo", ""), "*InvoiceDate": _d(r["date"]), "*DueDate": _d(r.get("due_date") if pd.notna(r.get("due_date")) else r["date"]),
        "InventoryItemCode": "", "*Description": r["description"], "*Quantity": 1, "*UnitAmount": _amount(sign * r["net"]),
        "Discount": "", "*AccountCode": r.get("account_code") or r["account"], "*TaxType": _tax("xero", settings, r["vat_code"], sales),
        "TaxAmount": _amount(sign * r["vat"]), "TrackingName1": settings.get("tracking_name", "") if r.get("tracking") else "",
        "TrackingOption1": r.get("tracking", ""), "Currency": "GBP"} for r in rows]


def xero_bills(entries, settings, **_):
    rows = _xero_lines(_ready(entries, "bill").to_dict("records"), settings)
    rows += _xero_lines(_ready(entries, "supplier_credit").to_dict("records"), settings, sign=-1)  # negative = credit note
    return pd.DataFrame(rows)


def xero_sales_invoices(entries, settings, sales=None, **_):
    s = sales[sales["status"] == "Ready"] if sales is not None and not sales.empty else pd.DataFrame()
    return pd.DataFrame([{
        "*ContactName": r["customer"], "EmailAddress": "", "*InvoiceNumber": r["invoice_number"],
        "Reference": r["po_number"], "*InvoiceDate": _d(r["date"]), "*DueDate": _d(r["due_date"]),
        "InventoryItemCode": "", "*Description": r["description"], "*Quantity": r["quantity"],
        "*UnitAmount": r["unit_price"], "Discount": "", "*AccountCode": settings.get("sales_account_code", "200"),
        "*TaxType": _tax("xero", settings, r["vat_code"], sales=True), "TaxAmount": _amount(r["vat"]),
        "Currency": "GBP"} for r in s.to_dict("records")])


def xero_card_statement(entries, settings, **_):
    e = _ready(entries, "card_expense")
    return pd.DataFrame([{
        "*Date": _d(r["date"]), "*Amount": _amount(-r["gross"]), "Payee": r["counterparty"], "Description": r["description"],
        "Reference": r["reference"], "Account code (suggested)": r.get("account_code") or r["account"],
        "Tax rate (suggested)": _tax("xero", settings, r["vat_code"])} for r in e.to_dict("records")])


def xero_journal(entries, settings, journal=None, **_):
    if journal is None or journal.empty:
        return pd.DataFrame()
    codes = settings.get("_account_codes", {})
    return pd.DataFrame([{
        "*Narration": settings.get("journal_number") or r["reference"], "*Date": _d(r["date"]), "Description": r["description"],
        "*AccountCode": codes.get(r["account"], r["account"]), "*TaxRate": "No VAT",
        "*Amount": _amount(r["debit"] - r["credit"]), "TrackingName1": "Department" if r.get("class") else "",
        "TrackingOption1": r.get("class", "")} for r in journal.to_dict("records")])

# ----------------------------------------------------------------- Sage 50

_SAGE_TYPES = {"bill": "PI", "supplier_credit": "PC", "card_expense": "BP", "sales_invoice": "SI", "sales_credit": "SC"}


def sage_transactions(entries, settings, journal=None, sales=None, **_):
    rows = []
    for r in (entries.to_dict("records") if entries is not None and not entries.empty else []):
        if r["status"] != "Ready" or r["kind"] not in _SAGE_TYPES:
            continue
        acct = settings.get("card_bank_nominal", "1240") if r["kind"] == "card_expense" else r.get("supplier_ref") or r["counterparty"][:8].upper()
        rows.append({"Type": _SAGE_TYPES[r["kind"]], "Account Reference": acct, "Nominal A/C Ref": r.get("account_code") or r["account"],
                     "Department Code": r.get("tracking", ""), "Date": _d(r["date"]), "Reference": r["reference"],
                     "Details": r["description"][:60], "Net Amount": _amount(r["net"]),
                     "Tax Code": _tax("sage50", settings, r["vat_code"]), "Tax Amount": _amount(r["vat"]),
                     "Exchange Rate": "", "Extra Reference": r.get("memo", ""), "User Name": "", "Project Refn": ""})
    if sales is not None and not sales.empty:
        for r in sales[sales["status"] == "Ready"].to_dict("records"):
            rows.append({"Type": "SI", "Account Reference": r.get("customer_ref") or r["customer"][:8].upper(),
                         "Nominal A/C Ref": settings.get("sales_nominal", "4000"), "Department Code": "",
                         "Date": _d(r["date"]), "Reference": r["invoice_number"], "Details": r["description"][:60],
                         "Net Amount": _amount(r["net"]), "Tax Code": _tax("sage50", settings, r["vat_code"]),
                         "Tax Amount": _amount(r["vat"]), "Exchange Rate": "", "Extra Reference": r["po_number"],
                         "User Name": "", "Project Refn": ""})
    if journal is not None and not journal.empty:
        codes = settings.get("_account_codes", {})
        for r in journal.to_dict("records"):
            rows.append({"Type": "JD" if r["debit"] else "JC", "Account Reference": codes.get(r["account"], r["account"]),
                         "Nominal A/C Ref": codes.get(r["account"], r["account"]), "Department Code": r.get("class", ""),
                         "Date": _d(r["date"]), "Reference": settings.get("journal_number") or r["reference"],
                         "Details": r["description"][:60], "Net Amount": _amount(r["debit"] or r["credit"]),
                         "Tax Code": "T9", "Tax Amount": 0.0, "Exchange Rate": "", "Extra Reference": "",
                         "User Name": "", "Project Refn": ""})
    return pd.DataFrame(rows)


def payroll_hours_csv(entries, settings, hours=None, **_):
    if hours is None or hours.empty:
        return pd.DataFrame()
    out = hours.copy()
    out["Week Commencing"] = out["Week commencing"].map(_d)
    return out[["Employee ID", "Employee", "Week Commencing", "Basic hours", "Overtime hours", "Weekend hours",
                "Total hours", "Hourly rate", "Gross pay (est.)"]]


# key: (system, builder, label, file stem, help)
EXPORTS = {
    "quickbooks_bills": ("quickbooks", qb_bills, "QuickBooks bills (CSV)", "quickbooks-bills",
                         "Supplier invoices for QuickBooks Online's bill import"),
    "quickbooks_supplier_credits": ("quickbooks", qb_supplier_credits, "QuickBooks supplier credits (CSV)",
                                    "quickbooks-supplier-credits", "Credit notes, to post as supplier credits"),
    "quickbooks_expenses": ("quickbooks", qb_expenses, "QuickBooks card expenses (CSV)", "quickbooks-card-expenses",
                            "Coded card spend, one line per VAT rate"),
    "quickbooks_journal": ("quickbooks", qb_journal, "QuickBooks payroll journal (CSV)", "quickbooks-payroll-journal",
                           "Balanced journal for QuickBooks Online's journal import"),
    "quickbooks_invoices": ("quickbooks", qb_invoices, "QuickBooks sales invoices (CSV)", "quickbooks-sales-invoices",
                            "Sales invoices for QuickBooks Online's invoice import"),
    "xero_bills": ("xero", xero_bills, "Xero bills (CSV)", "xero-bills", "Xero purchases import; credit notes as negative lines"),
    "xero_sales_invoices": ("xero", xero_sales_invoices, "Xero sales invoices (CSV)", "xero-sales-invoices", "Xero sales invoice import"),
    "xero_card_statement": ("xero", xero_card_statement, "Xero card statement (CSV)", "xero-card-statement",
                            "Card lines with suggested account and tax rate"),
    "xero_journal": ("xero", xero_journal, "Xero manual journal (CSV)", "xero-manual-journal", "Payroll journal for Xero"),
    "sage50_transactions": ("sage50", sage_transactions, "Sage 50 transactions (CSV)", "sage50-transactions",
                            "Audit trail import: PI, PC, SI, BP and journal lines"),
    "payroll_hours": ("any", payroll_hours_csv, "Payroll hours (CSV)", "payroll-hours", "Hours per employee per week for payroll"),
}


def build_exports(config: dict, entries: pd.DataFrame, *, journal=None, sales=None, hours=None,
                  chart_codes: dict | None = None, stem: str = "") -> list[ExportFile]:
    system = config.get("accounting_system", "quickbooks")
    keys = config.get("exports") or [k for k, v in EXPORTS.items() if v[0] == system]
    settings = dict(config.get("export_settings") or {})
    settings["_account_codes"] = chart_codes or {}
    out = []
    for key in keys:
        if key not in EXPORTS:
            continue
        _, builder, label, file_stem, help_text = EXPORTS[key]
        frame = builder(entries, settings, journal=journal, sales=sales, hours=hours)
        if frame is None or frame.empty:
            continue
        out.append(ExportFile(key, label, f"{stem}{file_stem}.csv", frame, help_text))
    return out

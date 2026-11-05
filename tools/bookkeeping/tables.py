"""Structured inputs (CSV / Excel): what each kind of table looks like, how
its columns are recognised, and how an uploaded file is routed to a role.

Every role has default column aliases for common UK exports (bank and card
statements, QuickBooks / Xero / Sage lists, payroll bureau reports). A client
config can add aliases under ``tables.<role>.aliases`` without code changes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from tools.data_validation.loader import DataFileError, coerce_dates, coerce_numeric, map_columns, read_table

__all__ = ["DataFileError", "TableSpec", "TABLE_SPECS", "table_spec", "load_table", "detect_role", "norm_name"]


@dataclass
class TableSpec:
    role: str
    label: str
    required: list[str]
    aliases: dict[str, list[str]] = field(default_factory=dict)
    numeric: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # yes/no columns


def _spec(role, label, required, aliases, numeric=(), dates=(), flags=()) -> TableSpec:
    return TableSpec(role, label, list(required), aliases, list(numeric), list(dates), list(flags))


TABLE_SPECS: dict[str, TableSpec] = {s.role: s for s in [
    _spec("card_statement", "card statement", ["date", "description", "amount"], {
        "date": ["Transaction Date", "Date", "Posted Date", "Trans Date"],
        "description": ["Merchant", "Description", "Details", "Narrative", "Payee", "Transaction Description"],
        "amount": ["Amount", "Amount (GBP)", "Value", "GBP Amount", "Billing Amount"],
        "card_last4": ["Card", "Card Number", "Card ending", "Card No", "Card Last 4"],
        "cardholder": ["Cardholder", "Card Holder", "Cardholder Name", "Employee"],
        "reference": ["Reference", "Ref", "Transaction ID", "Transaction Reference"],
        "original_currency": ["Currency", "Original Currency", "Transaction Currency"],
        "original_amount": ["Original Amount", "Foreign Amount", "Transaction Amount"],
    }, numeric=["amount", "original_amount"], dates=["date"]),
    _spec("bank_statement", "bank statement", ["date", "description", "amount"], {
        "date": ["Date", "Transaction Date", "Posted Date", "Value Date"],
        "description": ["Description", "Details", "Narrative", "Payee", "Memo", "Transaction Description"],
        "amount": ["Amount", "Value", "Amount (GBP)", "Net Amount"],
        "reference": ["Reference", "Ref", "Transaction Reference"],
        "balance": ["Balance", "Running Balance"],
    }, numeric=["amount", "balance"], dates=["date"]),
    _spec("suppliers", "supplier list", ["name"], {
        "name": ["Supplier", "Supplier Name", "Name", "Company", "Contact Name", "Vendor"],
        "account_ref": ["Account Ref", "A/C Ref", "Supplier Ref", "Account Reference", "Code"],
        "default_account": ["Default Account", "Default Nominal", "Account", "Nominal", "Expense Account", "Category"],
        "vat_code": ["Default VAT", "VAT Code", "Tax Code", "Default Tax Code", "VAT"],
        "vat_number": ["VAT Number", "VAT Reg", "VAT Registration", "VAT No", "Tax Number"],
        "sort_code": ["Sort Code", "Bank Sort Code"],
        "account_number": ["Account Number", "Bank Account Number", "Bank Account"],
        "terms_days": ["Terms (days)", "Payment Terms", "Terms", "Terms Days"],
        "email": ["Email", "Accounts Email", "Email Address"],
        "contact": ["Contact", "Contact Person", "Accounts Contact"],
    }, numeric=["terms_days"]),
    _spec("customers", "customer list", ["name"], {
        "name": ["Customer", "Customer Name", "Name", "Client", "Company"],
        "account_ref": ["Account Ref", "A/C Ref", "Customer Ref", "Code"],
        "email": ["Email", "Accounts Email", "Email Address"],
        "contact": ["Contact", "Contact Person", "Accounts Contact"],
        "terms_days": ["Terms (days)", "Payment Terms", "Terms", "Terms Days"],
        "po_required": ["PO Required", "Requires PO", "PO Needed"],
        "credit_limit": ["Credit Limit", "Limit"],
    }, numeric=["terms_days", "credit_limit"], flags=["po_required"]),
    _spec("chart_of_accounts", "chart of accounts", ["name"], {
        "code": ["Code", "Account Code", "Nominal Code", "N/C", "Account No", "Number"],
        "name": ["Name", "Account Name", "Account", "Nominal Name", "Description"],
        "type": ["Type", "Account Type", "Category"],
        "description": ["Notes", "Detail Type", "Use for", "Guidance"],
    }),
    _spec("payroll", "payroll summary", ["employee", "gross", "net_pay"], {
        "employee_id": ["Employee ID", "Emp ID", "Payroll ID", "Works Number", "Employee Ref"],
        "employee": ["Employee", "Employee Name", "Name"],
        "department": ["Department", "Dept", "Cost Centre", "Cost Center"],
        "gross": ["Gross Pay", "Gross", "Total Gross"],
        "paye": ["PAYE Tax", "PAYE", "Tax", "Income Tax"],
        "employee_ni": ["Employee NI", "EE NI", "Employees NI", "NI (Employee)"],
        "employer_ni": ["Employer NI", "ER NI", "Employers NI", "NI (Employer)"],
        "employee_pension": ["Employee Pension", "EE Pension", "Pension (Employee)"],
        "employer_pension": ["Employer Pension", "ER Pension", "Pension (Employer)"],
        "student_loan": ["Student Loan", "Student Loan Deduction", "SL"],
        "other_deductions": ["Other Deductions", "Other", "Attachment of Earnings"],
        "net_pay": ["Net Pay", "Net", "Take Home Pay"],
    }, numeric=["gross", "paye", "employee_ni", "employer_ni", "employee_pension", "employer_pension",
                "student_loan", "other_deductions", "net_pay"]),
    _spec("sales_to_invoice", "work to invoice", ["customer", "description", "quantity", "unit_price"], {
        "customer": ["Customer", "Customer Name", "Client"],
        "date": ["Date", "Completed", "Completion Date", "Delivery Date", "Invoice Date"],
        "job": ["Job", "Job No", "Job Ref", "Order", "Order No", "Reference"],
        "description": ["Description", "Work Done", "Item Description", "Details"],
        "item": ["Item", "Product/Service", "Product", "Service"],
        "quantity": ["Quantity", "Qty", "Hours", "Units"],
        "unit_price": ["Unit Price", "Rate", "Price", "Unit Rate"],
        "vat_code": ["VAT Code", "VAT", "Tax Code", "VAT Rate"],
        "po_number": ["Customer PO", "PO Number", "PO", "Purchase Order", "Customer Order No"],
    }, numeric=["quantity", "unit_price"], dates=["date"]),
    _spec("open_invoices", "sales ledger (open invoices)", ["customer", "invoice_number", "amount"], {
        "customer": ["Customer", "Customer Name", "Client", "Account Name"],
        "account_ref": ["Account Ref", "A/C Ref", "Customer Ref"],
        "invoice_number": ["Invoice Number", "Invoice No", "Invoice", "Ref", "Reference", "Document No"],
        "invoice_date": ["Invoice Date", "Date", "Doc Date"],
        "due_date": ["Due Date", "Due"],
        "amount": ["Amount", "Gross", "Invoice Total", "Total", "Original Amount"],
        "paid": ["Paid", "Amount Paid", "Payments", "Allocated"],
        "project_ref": ["Project", "Job", "Project Ref", "Job Ref", "Site"],
        "status": ["Status", "Notes", "Comment", "Query"],
    }, numeric=["amount", "paid"], dates=["invoice_date", "due_date"]),
    _spec("timesheets", "timesheets", ["employee", "date"], {
        "employee_id": ["Employee ID", "Emp ID", "Payroll ID", "Works Number"],
        "employee": ["Employee", "Name", "Operative", "Employee Name"],
        "date": ["Date", "Work Date", "Day"],
        "start": ["Start", "Start Time", "Time In", "In"],
        "finish": ["Finish", "End", "End Time", "Time Out", "Out"],
        "break_minutes": ["Break (mins)", "Break", "Break Minutes", "Unpaid Break"],
        "hours": ["Hours", "Total Hours", "Hours Worked"],
        "job": ["Job", "Site", "Project", "Job Ref", "Contract"],
        "approved_by": ["Approved By", "Approved", "Supervisor", "Signed Off By"],
    }, numeric=["break_minutes", "hours"], dates=["date"]),
    _spec("employees", "employee list", ["employee"], {
        "employee_id": ["Employee ID", "Emp ID", "Payroll ID", "Works Number", "Employee Ref"],
        "employee": ["Employee", "Name", "Employee Name"],
        "hourly_rate": ["Hourly Rate", "Rate", "Pay Rate", "Basic Rate"],
        "contracted_hours": ["Contracted Hours", "Weekly Hours", "Contract Hours", "Standard Hours"],
        "department": ["Department", "Dept", "Team"],
        "overtime_multiplier": ["Overtime Rate", "OT Multiplier", "Overtime Multiplier"],
    }, numeric=["hourly_rate", "contracted_hours", "overtime_multiplier"]),
    _spec("purchase_orders", "purchase orders", ["po_number", "supplier", "net_amount"], {
        "po_number": ["PO Number", "PO", "PO No", "Order Number", "Purchase Order"],
        "supplier": ["Supplier", "Supplier Name", "Vendor"],
        "date": ["Date", "PO Date", "Order Date"],
        "net_amount": ["Net Amount", "Net", "Amount", "Order Value", "Value (net)"],
        "description": ["Description", "Details", "Items"],
        "job": ["Job", "Site", "Project", "Job Ref"],
        "status": ["Status"],
    }, numeric=["net_amount"], dates=["date"]),
    _spec("projects", "project register", ["project_ref", "project_name"], {
        "project_ref": ["Project Ref", "Project", "Job", "Job Ref", "Project Number", "Job Number"],
        "project_name": ["Project Name", "Name", "Job Name", "Description"],
        "client": ["Client", "Customer"],
        "site": ["Site", "Site Address", "Address", "Location"],
        "keywords": ["Keywords", "Also Known As", "Aliases"],
        "status": ["Status", "Job Status", "Project Status"],
    }),
    _spec("purchase_ledger", "purchase ledger", ["supplier", "reference", "amount"], {
        "supplier": ["Supplier", "Supplier Name", "Name"],
        "reference": ["Reference", "Invoice Number", "Invoice No", "Ref", "Document No"],
        "date": ["Date", "Invoice Date"],
        "amount": ["Amount", "Gross", "Total"],
    }, numeric=["amount"], dates=["date"]),
]}

# Upload routing: the first role whose required columns are all present wins,
# so the more specific shapes come first.
DETECT_ORDER = ["payroll", "timesheets", "sales_to_invoice", "open_invoices", "purchase_orders", "card_statement",
                "bank_statement", "purchase_ledger", "employees", "projects", "chart_of_accounts", "customers", "suppliers"]


def table_spec(role: str, config: dict | None = None) -> TableSpec:
    """Default spec for a role, with any extra aliases from ``config['tables'][role]``."""
    base = TABLE_SPECS[role]
    extra = ((config or {}).get("tables") or {}).get(role) or {}
    aliases = {k: list(v) for k, v in base.aliases.items()}
    for col, names in (extra.get("aliases") or {}).items():
        aliases[col] = list(names) + aliases.get(col, [])
    return TableSpec(role, extra.get("label", base.label), list(extra.get("required", base.required)), aliases,
                     base.numeric + list(extra.get("numeric", [])), base.dates + list(extra.get("dates", [])),
                     base.flags)


def norm_name(text) -> str:
    """Lower-case, letters and digits only (accents removed), common company suffixes removed."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and "))
    s = re.sub(r"\b(ltd|limited|plc|llp|the|and|co|company|uk|group)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_TRUE = {"yes", "y", "true", "1", "x", "required"}


def load_table(name: str, data: bytes, spec: TableSpec) -> pd.DataFrame:
    """Read one CSV/XLSX into canonical columns. Unparseable numbers become NaN
    (and are listed in ``df.attrs['bad_cells']``) rather than stopping the run."""
    raw = read_table(name, data)
    df = _map_debit_credit(raw)
    df = map_columns(df, spec.aliases, spec.required, name).reset_index(drop=True)
    bad: list[str] = []
    for col in spec.numeric:
        if col in df:
            before = df[col].copy()
            df[col], mask = coerce_numeric(_brackets_negative(df[col]))
            bad += [f"row {i + 2} {col} “{before[i]}”" for i in df.index[mask]]
    for col in spec.dates:
        if col in df:
            before = df[col].copy()
            df[col], mask = coerce_dates(df[col])
            bad += [f"row {i + 2} {col} “{before[i]}”" for i in df.index[mask]]
    for col in spec.flags:
        if col in df:
            df[col] = df[col].map(lambda v: str(v).strip().lower() in _TRUE)
    typed = set(spec.numeric) | set(spec.dates) | set(spec.flags)
    for col in df.columns:
        if col not in typed:  # plain text: blanks as "", numbers from Excel as text without ".0"
            df[col] = pd.Series([_text(v) for v in df[col]], index=df.index, dtype=object)
    df["_source"] = name
    df["_row"] = df.index + 2
    df.attrs["bad_cells"] = bad
    return df


def _text(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _brackets_negative(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    return series.map(lambda v: "-" + v.strip()[1:-1] if isinstance(v, str) and re.fullmatch(r"\s*\(.*\)\s*", v) else v)


def _map_debit_credit(df: pd.DataFrame) -> pd.DataFrame:
    """Bank exports with separate Debit/Credit (or Money out/Money in) columns get
    one signed Amount column: money out negative, money in positive."""
    cols = {re.sub(r"[^a-z]", "", c.lower()): c for c in df.columns}
    out_col = next((cols[k] for k in ("debit", "moneyout", "paidout", "withdrawals") if k in cols), None)
    in_col = next((cols[k] for k in ("credit", "moneyin", "paidin", "deposits") if k in cols), None)
    if out_col and in_col and "amount" not in cols:
        money_out, _ = coerce_numeric(_brackets_negative(df[out_col]))
        money_in, _ = coerce_numeric(_brackets_negative(df[in_col]))
        df = df.copy()
        df["Amount"] = money_in.fillna(0) - money_out.fillna(0)
    return df


def detect_role(name: str, data: bytes, config: dict, allowed: list[str] | None = None) -> str | None:
    """Work out what an uploaded table is from its column headings."""
    try:
        raw = _map_debit_credit(read_table(name, data))
    except DataFileError:
        return None
    for role in DETECT_ORDER:
        if allowed is not None and role not in allowed:
            continue
        spec = table_spec(role, config)
        try:
            mapped = map_columns(raw.head(3), spec.aliases, spec.required, name)
        except DataFileError:
            continue
        if role == "card_statement" and not ({"card_last4", "cardholder"} & set(mapped.columns)):
            continue  # a plain bank statement
        hints = DETECT_HINTS.get(role)
        if hints:
            headers = " ".join(str(c).lower() for c in raw.columns)
            if not (set(hints[0]) & set(mapped.columns) or any(w in headers for w in hints[1])):
                continue
        return role
    return None


# Roles with loose required columns need one of these columns or header words to be recognised.
DETECT_HINTS = {
    "customers": (["po_required", "credit_limit"], ["customer", "client"]),
    "suppliers": (["vat_number", "sort_code", "account_number", "default_account"], ["supplier", "vendor"]),
    "chart_of_accounts": (["code", "type"], ["nominal", "account"]),
    "employees": (["hourly_rate", "contracted_hours"], ["employee"]),
}

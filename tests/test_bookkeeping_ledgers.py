"""Bookkeeping engine: payroll, timesheets, sales invoices, aged debtors, POs,
filing, exports and the month-end checklist."""

import io
import zipfile

import pandas as pd

from tools.bookkeeping import month_end
from tools.bookkeeping.exports import build_exports
from tools.bookkeeping.filing import file_documents, filing_zip
from tools.bookkeeping.orders import match_invoices_to_pos
from tools.bookkeeping.payroll import check_payroll, payroll_journal, timesheet_hours
from tools.bookkeeping.sales import aged_debtors, bucket_label, chase_groups, raise_invoices

T = pd.Timestamp

# ------------------------------------------------------------------ payroll


def _payroll(net_b=1570.0):
    return pd.DataFrame([
        {"employee": "A", "department": "Office", "gross": 2000.0, "paye": 190.0, "employee_ni": 76.0, "employer_ni": 237.0,
         "employee_pension": 74.0, "employer_pension": 44.4, "student_loan": 0.0, "net_pay": 1660.0},
        {"employee": "B", "department": "Ops", "gross": 2000.0, "paye": 190.0, "employee_ni": 76.0, "employer_ni": 237.0,
         "employee_pension": 74.0, "employer_pension": 44.4, "student_loan": 90.0, "net_pay": net_b},
        {"employee": "TOTAL", "department": "", "gross": 4000.0, "paye": 380.0, "employee_ni": 152.0, "employer_ni": 474.0,
         "employee_pension": 148.0, "employer_pension": 88.8, "student_loan": 90.0, "net_pay": 1660.0 + net_b},
    ])


def test_payroll_journal_balances_when_payslips_reconcile():
    emp, findings, totals = check_payroll(_payroll())
    assert findings == [] and totals["employees"] == 2 and totals["gross"] == 4000.0
    journal, diff = payroll_journal(emp, date=T("2026-10-31"))
    assert diff == 0 and round(journal["debit"].sum(), 2) == round(journal["credit"].sum(), 2) == 4562.8
    liability = journal.set_index("account")["credit"]
    assert liability["PAYE and NI payable"] == 380 + 152 + 474 + 90
    assert liability["Pension payable"] == 148 + 88.8 and liability["Net wages payable"] == 3230.0
    assert set(journal["class"]) >= {"Office", "Ops"}  # wages split by department


def test_payroll_net_pay_error_goes_to_suspense():
    emp, findings, _ = check_payroll(_payroll(net_b=1670.0))
    assert [f.check_id for f in findings] == ["payroll_net_mismatch"]
    assert findings[0].subject == "B" and findings[0].amount == 100.0
    journal, diff = payroll_journal(emp, date=T("2026-10-31"))
    assert diff == -100.0
    assert journal.set_index("account").loc["Suspense", "debit"] == 100.0
    assert round(journal["debit"].sum(), 2) == round(journal["credit"].sum(), 2)


def test_payroll_report_total_is_checked():
    df = _payroll()
    df.loc[2, "gross"] = 4100.0
    _, findings, _ = check_payroll(df)
    assert [f.check_id for f in findings] == ["payroll_total_mismatch"]

# --------------------------------------------------------------- timesheets


def test_timesheet_hours_overtime_and_checks():
    rows = []
    for day in range(5, 10):  # Mon 5 Oct - Fri 9 Oct 2026, 9 hours a day
        rows.append({"employee": "Sam", "date": T(f"2026-10-{day:02d}"), "start": "07:30", "finish": "17:00",
                     "break_minutes": 30.0, "hours": float("nan"), "approved_by": "JB", "_source": "t.csv"})
    rows.append({"employee": "Sam", "date": T("2026-10-10"), "start": "06:00", "finish": "20:00", "break_minutes": 0.0,
                 "hours": 14.0, "approved_by": "", "_source": "t.csv"})  # Saturday, long, unapproved
    rows.append({"employee": "Pat", "date": T("2026-10-05"), "start": "08:00", "finish": "16:00", "break_minutes": 30.0,
                 "hours": 8.0, "approved_by": "JB", "_source": "t.csv"})  # stated 8 but 7.5 worked; not on the list
    employees = pd.DataFrame([{"employee": "Sam", "employee_id": "E1", "hourly_rate": 15.0, "contracted_hours": 40.0}])
    checked, summary, findings = timesheet_hours(pd.DataFrame(rows), employees, {"weekend_multiplier": 1.5})
    sam = summary.set_index("Employee").loc["Sam"]
    assert (sam["Basic hours"], sam["Overtime hours"], sam["Weekend hours"]) == (40.0, 5.0, 14.0)
    assert sam["Gross pay (est.)"] == 40 * 15 + 5 * 15 * 1.5 + 14 * 15 * 1.5
    kinds = sorted(f.check_id for f in findings)
    assert kinds == ["excess_hours", "hours_mismatch", "missing_approval", "unknown_employee"]

# -------------------------------------------------------------------- sales


def test_raise_invoices_groups_jobs_and_holds_missing_po():
    customers = pd.DataFrame([{"name": "Brightwater Ltd", "terms_days": 30, "po_required": True},
                              {"name": "Lakeside Practice", "terms_days": 14, "po_required": False}])
    work = pd.DataFrame([
        {"customer": "Brightwater Ltd", "job": "J1", "po_number": "PO-1", "description": "Visit", "quantity": 4.0, "unit_price": 185.0, "vat_code": "S"},
        {"customer": "Brightwater Ltd", "job": "J1", "po_number": "PO-1", "description": "Parts", "quantity": 1.0, "unit_price": 96.4, "vat_code": "S"},
        {"customer": "Brightwater Ltd", "job": "J2", "po_number": "", "description": "Extra", "quantity": 1.0, "unit_price": 100.0, "vat_code": "S"},
        {"customer": "Lakeside Practice", "job": "J3", "po_number": "", "description": "Contract", "quantity": 1.0, "unit_price": 420.0, "vat_code": "Z"},
    ])
    lines, findings = raise_invoices(work, customers, invoice_date=T("2026-10-31"), first_number=100, prefix="INV-")
    inv = lines.groupby("invoice_number").agg(gross=("gross", "sum"), status=("status", "first"), due=("due_date", "first"))
    assert list(inv.index) == ["INV-100", "INV-101", "INV-102"]
    assert round(inv.loc["INV-100", "gross"], 2) == round((740 + 96.4) * 1.2, 2) and inv.loc["INV-100", "status"] == "Ready"
    assert inv.loc["INV-101", "status"] == "Held"  # PO required, none given
    assert inv.loc["INV-102", "gross"] == 420.0 and inv.loc["INV-102", "due"] == T("2026-11-14")
    assert [(f.check_id, f.reference) for f in findings] == [("po_missing", "J2")]

# ------------------------------------------------------------------ debtors


def test_aged_debtors_buckets_receipts_disputes_and_chase_tiers():
    as_of = T("2026-11-05")
    invoices = pd.DataFrame([
        {"customer": "Acme", "invoice_number": "1001", "invoice_date": T("2026-10-20"), "due_date": T("2026-11-19"), "amount": 500.0, "paid": 0.0, "status": ""},
        {"customer": "Acme", "invoice_number": "0990", "invoice_date": T("2026-09-01"), "due_date": T("2026-10-01"), "amount": 300.0, "paid": 100.0, "status": ""},
        {"customer": "Bolt", "invoice_number": "0950", "invoice_date": T("2026-07-01"), "due_date": T("2026-07-31"), "amount": 800.0, "paid": 0.0, "status": ""},
        {"customer": "Bolt", "invoice_number": "0960", "invoice_date": T("2026-08-01"), "due_date": T("2026-08-31"), "amount": 200.0, "paid": 0.0, "status": "Disputed - wrong site"},
        {"customer": "Cole", "invoice_number": "0970", "invoice_date": T("2026-09-01"), "due_date": T("2026-10-01"), "amount": 120.0, "paid": 0.0, "status": ""},
    ])
    receipts = pd.DataFrame([{"date": T("2026-11-02"), "description": "COLE LTD INV 0970", "amount": 120.0, "reference": ""},
                             {"date": T("2026-11-03"), "description": "UNKNOWN PAYER", "amount": 55.0, "reference": ""}])
    items, summary, findings = aged_debtors(invoices, as_of=as_of, receipts=receipts)
    by_inv = items.set_index("invoice_number")
    assert by_inv.loc["1001", "bucket"] == "Current" and by_inv.loc["1001", "chase_tier"] == ""
    assert by_inv.loc["0990", "outstanding"] == 200.0 and by_inv.loc["0990", "chase_tier"] == "Second reminder"
    assert by_inv.loc["0950", "bucket"] == "Over 90 days" and by_inv.loc["0950", "chase_tier"] == "Final notice"
    assert by_inv.loc["0960", "chase_tier"] == ""  # disputed: not chased
    assert by_inv.loc["0970", "outstanding"] == 0.0  # paid by the bank receipt quoting the invoice number
    kinds = sorted(f.check_id for f in findings)
    assert kinds == ["disputed_invoice", "final_notice", "part_payment", "unallocated_payment"]
    assert summary.set_index("Customer").loc["Bolt", "Total outstanding"] == 1000.0
    letters = {c["customer"]: c for c in chase_groups(items, None)}
    assert set(letters) == {"Acme", "Bolt"} and letters["Bolt"]["tier"] == "Final notice"
    assert [i["invoice"] for i in letters["Bolt"]["invoices"]] == ["0950"]
    assert bucket_label(45, [0, 30, 60, 90]) == "31–60 days"

# ------------------------------------------------------------ orders/filing


def _inv(doc_id, supplier, number, net, po=""):
    return {"doc_id": doc_id, "doc_type": "invoice", "counterparty": supplier, "document_number": number,
            "document_date": T("2026-10-10"), "net_total": net, "gross_total": net * 1.2, "po_number": po, "file": f"{number}.pdf"}


def test_invoices_matched_to_purchase_orders():
    pos = pd.DataFrame([{"po_number": "PO-100", "supplier": "Acme", "net_amount": 500.0},
                        {"po_number": "PO-101", "supplier": "Bolt", "net_amount": 200.0},
                        {"po_number": "PO-102", "supplier": "Cole", "net_amount": 80.0}])
    docs = [_inv("D1", "Acme", "A1", 500.0, "po 100"), _inv("D2", "Bolt", "B1", 260.0, "PO-101"),
            _inv("D3", "Cole", "C1", 80.0), _inv("D4", "Dane", "X1", 10.0), _inv("D5", "Eden", "E1", 10.0, "PO-999")]
    table, findings = match_invoices_to_pos(docs, pos)
    status = dict(zip(table["Invoice"], table["Status"]))
    assert status == {"A1": "Matched", "B1": "Over PO value", "C1": "Matched", "X1": "No PO", "E1": "PO not found"}
    assert sorted(f.check_id for f in findings) == ["invoice_without_po", "po_not_found", "po_overbilled"]


def test_documents_filed_by_reference_keyword_or_left_for_a_person():
    projects = pd.DataFrame([{"project_ref": "P-2041", "project_name": "Riverside Flats", "site": "Riverside Road"},
                             {"project_ref": "P-2050", "project_name": "School Roof", "site": "Oak Lane"}])
    docs = [{"doc_id": "D1", "file": "a.pdf", "doc_type": "contract", "counterparty": "Acme", "document_number": "",
             "document_date": T("2026-10-01"), "project_reference": "P-2041", "summary": ""},
            {"doc_id": "D2", "file": "b.eml", "doc_type": "correspondence", "counterparty": "Bolt", "document_number": "",
             "document_date": T("2026-10-02"), "project_reference": "", "summary": ""},
            {"doc_id": "D3", "file": "c.eml", "doc_type": "correspondence", "counterparty": "Cole", "document_number": "",
             "document_date": None, "project_reference": "P-9999", "summary": ""}]
    texts = {"D1": "", "D2": "Access to the Oak Lane site from Monday", "D3": "nothing useful"}
    index, findings = file_documents(docs, texts, projects)
    assert index["Project"].tolist() == ["P-2041", "P-2050", ""]
    assert index["Folder"].tolist()[:2] == ["P-2041 Riverside Flats/Contracts", "P-2050 School Roof/Correspondence"]
    assert [f.check_id for f in findings] == ["unfiled_document"]
    z = zipfile.ZipFile(io.BytesIO(filing_zip(index, {"a.pdf": b"%PDF", "b.eml": b"x", "c.eml": b"y"})))
    assert "P-2041 Riverside Flats/Contracts/2026-10-01_Contract_Acme.pdf" in z.namelist() and "filing-index.csv" in z.namelist()

# ------------------------------------------------------------------ exports


def _entries():
    base = {"date": T("2026-10-03"), "due_date": T("2026-11-02"), "terms_days": 30, "counterparty": "Acme", "account": "Office supplies",
            "account_code": "6230", "description": "Paper", "tracking": "", "memo": "", "supplier_ref": "ACME01"}
    return pd.DataFrame([
        {**base, "kind": "bill", "reference": "A-1", "net": 100.0, "vat": 20.0, "gross": 120.0, "vat_code": "S", "status": "Ready"},
        {**base, "kind": "bill", "reference": "A-2", "net": 50.0, "vat": 10.0, "gross": 60.0, "vat_code": "S", "status": "Held"},
        {**base, "kind": "supplier_credit", "reference": "CN-1", "net": 10.0, "vat": 2.0, "gross": 12.0, "vat_code": "S", "status": "Ready"},
        {**base, "kind": "card_expense", "reference": "T-01", "net": 64.5, "vat": 0.0, "gross": 64.5, "vat_code": "Z", "status": "Ready"},
    ])


def test_quickbooks_exports_leave_out_held_entries():
    files = {f.key: f.frame for f in build_exports({"accounting_system": "quickbooks"}, _entries())}
    assert set(files) == {"quickbooks_bills", "quickbooks_supplier_credits", "quickbooks_expenses"}
    bills = files["quickbooks_bills"]
    assert bills["Bill No"].tolist() == ["A-1"] and bills["Line Tax Code"].tolist() == ["20.0% S"]
    assert bills["Bill Date"].iloc[0] == "03/10/2026" and bills["Terms"].iloc[0] == "Net 30"
    assert files["quickbooks_expenses"]["Line Tax Code"].iloc[0] == "0.0% Z"


def test_xero_and_sage_exports():
    xero = {f.key: f.frame for f in build_exports({"accounting_system": "xero"}, _entries())}
    bills = xero["xero_bills"]
    assert bills["*UnitAmount"].tolist() == [100.0, -10.0]  # credit note as a negative line
    assert bills["*AccountCode"].iloc[0] == "6230" and bills["*TaxType"].iloc[0] == "20% (VAT on Expenses)"
    sage = build_exports({"accounting_system": "sage50", "export_settings": {"card_bank_nominal": "1240"}}, _entries())[0].frame
    assert sage["Type"].tolist() == ["PI", "PC", "BP"] and sage["Tax Code"].tolist() == ["T1", "T1", "T0"]
    assert sage["Account Reference"].tolist() == ["ACME01", "ACME01", "1240"]

# ------------------------------------------------------------------ checklist


def test_month_end_checklist_statuses():
    config = {"month_end": {"checklist": [{"id": "purchase_invoices"}, {"id": "card_matched"}, {"id": "timesheets_approved"},
                                          {"label": "Reconcile the bank", "manual": True}]}}
    facts = {"purchase_docs": 10, "purchase_ready": 8, "purchase_held": 2, "card_txns": 5, "card_matched": 5}
    out = month_end.checklist(config, facts, {"arithmetic": ["EX-01"]})
    assert out["Status"].tolist() == ["Action needed", "Done", "To do"]  # timesheets item skipped: not in this run
    assert out["Exceptions"].iloc[0] == "EX-01" and "8 of 10" in out["Detail"].iloc[0]

"""The bookkeeping engine with the module combinations the other bookkeeping briefs
need, on tiny in-memory inputs, in mock mode (pattern reader + templates)."""

import io

import pandas as pd
import pytest

from core.claude import ClaudeClient
from tools.bookkeeping import pipeline, reports
from tools.bookkeeping.pipeline import RunInputs
from tools.bookkeeping.vat import format_vat_number, make_gb_vat_number


def _pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    for i, line in enumerate(lines):
        c.drawString(50, 800 - 15 * i, line)
    c.save()
    return buf.getvalue()


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


INVOICE = _pdf(["Acme Supplies Ltd", f"VAT Reg No: {format_vat_number(make_gb_vat_number('3124570'))}", "INVOICE",
                "Invoice number: AC-1001", "Invoice date: 05/10/2026",
                "Your order ref: PO-100", "Job: P-2041", "Subtotal £100.00", "VAT @ 20% £20.00", "Total due £120.00"])
CHART = _csv(pd.DataFrame({"Account Code": ["5000", "6230", "9999"], "Account Name": ["Purchases", "Office supplies", "Suspense"],
                           "Account Type": ["Cost of sales", "Expense", "Suspense"]}))
SUPPLIERS = _csv(pd.DataFrame({"Supplier": ["Acme Supplies Ltd"], "Default Account": ["Purchases"], "VAT Number": [""],
                               "Sort Code": [""], "Account Number": [""]}))
BASE = {"headline": "X: built as a prototype for Y", "company": {"name": "Demo Ltd"}, "period": {"start": "2026-10-01", "end": "2026-10-31"}}


def _run(config: dict, inputs: RunInputs):
    return pipeline.run(inputs, {**BASE, **config}, ClaudeClient(mock=True))


def test_xero_bookkeeping_with_vat_return():
    sales = _csv(pd.DataFrame({"Customer": ["Bolt Ltd"], "Description": ["Solder paste"], "Qty": [10], "Unit Price": [12.5],
                               "VAT Code": ["S"], "Job": ["S-1"]}))
    cfg = {"accounting_system": "xero", "modules": {"vat_return": True}}
    r = _run(cfg, RunInputs(documents=[("acme.pdf", INVOICE)], tables={
        "chart_of_accounts": [("chart.csv", CHART)], "suppliers": [("suppliers.csv", SUPPLIERS)],
        "sales_to_invoice": [("sales.csv", sales)]}, period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31"))))
    assert {x.key for x in r.exports} == {"xero_bills", "xero_sales_invoices"}
    boxes = r.vat_return.set_index("Box")["Amount (£)"]
    assert boxes[1] == 25.0 and boxes[4] == 20.0 and boxes[5] == 5.0  # sales VAT 25, purchase VAT 20
    assert "VAT return workings" in reports.sheets(r)


def test_debtors_chasing_and_filing():
    ledger = _csv(pd.DataFrame({"Customer": ["Kent Build Ltd", "Kent Build Ltd", "Weald Homes"],
                                "Invoice No": ["5001", "5002", "5003"],
                                "Invoice Date": ["01/07/2026", "15/09/2026", "01/10/2026"],
                                "Due Date": ["31/07/2026", "15/10/2026", "31/10/2026"],
                                "Amount": [1200.0, 600.0, 300.0], "Paid": [0, 0, 0], "Project": ["P-2041", "P-2041", "P-2050"],
                                "Status": ["", "Disputed - snagging", ""]}))
    bank = _csv(pd.DataFrame({"Date": ["02/11/2026"], "Description": ["WEALD HOMES 5003"], "Amount": [300.0]}))
    projects = _csv(pd.DataFrame({"Project Ref": ["P-2041", "P-2050"], "Project Name": ["Riverside Flats", "School Roof"],
                                  "Site": ["Riverside Road", "Oak Lane"]}))
    customers = _csv(pd.DataFrame({"Customer": ["Kent Build Ltd", "Weald Homes"], "Email": ["a@x.example", ""], "Credit Limit": [5000, 1000]}))
    letter = b"From: Site Office <s@x.example>\nSubject: Riverside Road access\n\nScaffold at Riverside Road comes down on Friday.\n"
    cfg = {"accounting_system": "xero", "modules": {"filing": True}, "filing": {"reference_pattern": r"P-\d{4}"}}
    r = _run(cfg, RunInputs(documents=[("site-letter.eml", letter), ("acme.pdf", INVOICE)], as_of=pd.Timestamp("2026-11-05"),
                            tables={"open_invoices": [("ledger.csv", ledger)], "bank_statement": [("bank.csv", bank)],
                                    "projects": [("projects.csv", projects)], "customers": [("customers.csv", customers)]}))
    items = r.debtors.set_index("invoice_number")
    assert items.loc["5001", "chase_tier"] == "Final notice" and items.loc["5002", "chase_tier"] == ""
    assert items.loc["5003", "outstanding"] == 0.0
    assert [l["key"] for l in r.letters if l["recipient_type"] == "customer"] == ["customer:Kent Build Ltd"]
    assert set(r.filing["Project"]) == {"P-2041"}  # letter by site keyword, invoice by reference in the text
    assert any(f.file_name.endswith("filed-documents.zip") for f in r.downloads)
    assert {"disputed_invoice", "final_notice"} <= {f.check_id for f in r.findings}


def test_timesheets_purchase_orders_and_sage():
    ts = _csv(pd.DataFrame({"Employee": ["Dai Evans"] * 5 + ["Unknown Person"],
                            "Date": [f"{d:02d}/10/2026" for d in range(5, 10)] + ["05/10/2026"],
                            "Start": ["07:00"] * 6, "Finish": ["17:30"] * 6, "Break (mins)": [30] * 6,
                            "Approved By": ["GH"] * 5 + [""]}))
    employees = _csv(pd.DataFrame({"Employee": ["Dai Evans"], "Employee ID": ["CF01"], "Hourly Rate": [14.0], "Contracted Hours": [45]}))
    pos = _csv(pd.DataFrame({"PO Number": ["PO-100"], "Supplier": ["Acme Supplies Ltd"], "Net Amount": [80.0]}))
    cfg = {"accounting_system": "sage50", "exports": ["sage50_transactions", "payroll_hours"]}
    r = _run(cfg, RunInputs(documents=[("acme.pdf", INVOICE)], tables={
        "timesheets": [("ts.csv", ts)], "employees": [("emp.csv", employees)], "purchase_orders": [("po.csv", pos)],
        "chart_of_accounts": [("chart.csv", CHART)], "suppliers": [("suppliers.csv", SUPPLIERS)]},
        period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31"))))
    dai = r.hours.set_index("Employee").loc["Dai Evans"]
    assert (dai["Basic hours"], dai["Overtime hours"]) == (45.0, 5.0)
    assert {"unknown_employee", "missing_approval", "po_overbilled"} <= {f.check_id for f in r.findings}
    assert r.entries["status"].tolist() == ["Held"]  # over the PO value: held out of the Sage file
    assert {x.key for x in r.exports} == {"payroll_hours"}
    assert "Hours for payroll" in reports.sheets(r)


def test_statement_reconciliation_and_property_analysis(monkeypatch):
    statement_text = ("Acme Supplies Ltd\nSTATEMENT OF ACCOUNT\nBalance due £170.00\n"
                      "AC-1001 05/10/2026 £120.00\nAC-0999 20/09/2026 £50.00\n")
    projects = _csv(pd.DataFrame({"Project Ref": ["P-2041"], "Project Name": ["12 High Street"]}))
    cfg = {"modules": {"statements": True}, "analysis": {"tracking_label": "Property"}}
    from tools.bookkeeping import ai

    real = ai.pattern_extract

    def fake_extract(doc):  # the pattern reader cannot read statement lines; stand in for Claude here
        out = real(doc)
        if "STATEMENT" in doc.text:
            out.update(doc_type="statement", counterparty="Acme Supplies Ltd", statement_lines=[
                {"date": "2026-10-05", "reference": "AC-1001", "description": "Invoice", "amount": 120.0},
                {"date": "2026-09-20", "reference": "AC-0999", "description": "Invoice", "amount": 50.0}])
        else:
            out["project_reference"] = "P-2041"
        return out

    monkeypatch.setattr(ai, "pattern_extract", fake_extract)
    r = _run(cfg, RunInputs(documents=[("acme.pdf", INVOICE), ("statement.txt", statement_text.encode())],
                            tables={"chart_of_accounts": [("chart.csv", CHART)], "suppliers": [("suppliers.csv", SUPPLIERS)],
                                    "projects": [("p.csv", projects)]},
                            period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31"))))
    status = dict(zip(r.statements["Statement ref"], r.statements["Status"]))
    assert status == {"AC-1001": "Agrees", "AC-0999": "Not in our records"}
    assert [l["key"] for l in r.letters] == ["supplier:Acme Supplies Ltd"]
    totals = reports.tracking_totals(r)
    assert totals["Property"].tolist() == ["P-2041"] and "Totals by property" in reports.sheets(r)


@pytest.mark.parametrize("system", ["quickbooks", "xero", "sage50"])
def test_every_system_exports_something(system):
    r = _run({"accounting_system": system}, RunInputs(documents=[("acme.pdf", INVOICE)], tables={
        "chart_of_accounts": [("chart.csv", CHART)], "suppliers": [("suppliers.csv", SUPPLIERS)]},
        period=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31"))))
    assert r.exports and all(not x.frame.empty for x in r.exports)

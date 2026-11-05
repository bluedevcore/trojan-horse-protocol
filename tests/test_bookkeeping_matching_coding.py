"""Bookkeeping engine: matching, coding rules, supplier checks, table routing and findings."""

import pandas as pd

from tools.bookkeeping.checks import Finding, finalise, findings_frame
from tools.bookkeeping.coding import Rules, SupplierBook, chart_from_frame, code_from_rules, supplier_vat_checks
from tools.bookkeeping.matching import (MatchSettings, clean_descriptor, match_card_to_documents, name_similarity,
                                        reconcile_statement)
from tools.bookkeeping.tables import detect_role, load_table, table_spec
from tools.bookkeeping.vat import make_gb_vat_number

# ----------------------------------------------------------------- matching


def test_card_descriptors_are_cleaned_and_compared():
    assert clean_descriptor("SQ *THE COPPER KETTLE TELFORD GB") == "copper kettle"
    assert name_similarity("SQ *EMBER & OAK CAFE TELFORD", "Ember & Oak Café") >= 0.9
    assert name_similarity("MERECROFT TYRE & AUTO", "Wellington Road Service Station") < 0.4


def _doc(doc_id, name, gross, date, currency="GBP", number=""):
    return {"doc_id": doc_id, "counterparty": name, "gross_total": gross, "document_date": pd.Timestamp(date),
            "currency": currency, "document_number": number}


def _txns(rows):
    return pd.DataFrame([{"txn_id": t, "date": pd.Timestamp(d), "description": desc, "amount": a,
                          "original_currency": oc, "original_amount": oa} for t, d, desc, a, oc, oa in rows])


def test_card_matching_exact_near_foreign_and_one_to_one():
    txns = _txns([
        ("T-1", "2026-10-03", "WELLINGTON RD SERVICE STN", 60.00, "", None),
        ("T-2", "2026-10-08", "SQ *EMBER & OAK CAFE", 43.40, "", None),  # tip added
        ("T-3", "2026-10-13", "LAYOUTLY INC", 11.86, "USD", 14.99),  # foreign currency
        ("T-4", "2026-10-20", "WELLINGTON RD SERVICE STN", 60.00, "", None),  # same amount, second visit
        ("T-5", "2026-10-09", "MERECROFT TYRE & AUTO", 126.00, "", None),  # no receipt
    ])
    docs = [_doc("D-1", "Wellington Road Service Station", 60.00, "2026-10-03"),
            _doc("D-2", "Ember & Oak Café", 38.40, "2026-10-07"),
            _doc("D-3", "Layoutly Inc.", 14.99, "2026-10-13", currency="USD"),
            _doc("D-4", "Wellington Road Service Station", 60.00, "2026-10-20"),
            _doc("D-5", "Unrelated Shop", 126.00, "2026-08-01")]  # right amount, far too early
    pairs = {t: (d, info) for t, d, info in match_card_to_documents(txns, docs, MatchSettings())}
    assert pairs["T-1"][0] == "D-1" and pairs["T-4"][0] == "D-4"  # dates decide between equal amounts
    assert pairs["T-2"][0] == "D-2" and pairs["T-2"][1]["near"] and pairs["T-2"][1]["difference"] == 5.0
    assert pairs["T-3"][0] == "D-3" and pairs["T-3"][1]["exact"] and pairs["T-3"][1]["foreign"]
    assert "T-5" not in pairs


def test_statement_reconciliation():
    statement = {"doc_id": "S-1", "counterparty": "Acme Ltd", "statement_lines": [
        {"reference": "A-1", "date": pd.Timestamp("2026-10-01"), "amount": 120.0},
        {"reference": "A-2", "date": pd.Timestamp("2026-10-05"), "amount": 99.0},
        {"reference": "A-3", "date": pd.Timestamp("2026-10-09"), "amount": 50.0}]}
    docs = [{"doc_id": "D-1", "doc_type": "invoice", "counterparty": "Acme Limited", "document_number": "A-1", "gross_total": 120.0},
            {"doc_id": "D-2", "doc_type": "invoice", "counterparty": "Acme Ltd", "document_number": "A-2", "gross_total": 90.0},
            {"doc_id": "D-4", "doc_type": "invoice", "counterparty": "Acme Ltd", "document_number": "A-4", "gross_total": 10.0}]
    status = dict(zip(reconcile_statement(statement, docs)["Statement ref"].replace("", "D-4"),
                      reconcile_statement(statement, docs)["Status"]))
    assert status == {"A-1": "Agrees", "A-2": "Amount differs", "A-3": "Not in our records",
                      "D-4": "Received, not on statement"}

# ------------------------------------------------------------------- coding


CHART = chart_from_frame(pd.DataFrame({"code": ["6300", "6600", "9999"], "name": ["Motor expenses", "Bank charges", "Suspense"]}))


def test_keyword_rules_and_chart_resolution():
    rules = Rules([{"match": "SERVICE STN|FUEL", "account": "motor expenses", "vat_code": "S"},
                   {"match": "FEE", "account": "6600", "vat_code": "E", "receipt_needed": False},
                   {"match": "NOWHERE", "account": "Not in chart"}])
    fuel = code_from_rules("WELLINGTON RD SERVICE STN", rules, CHART)
    assert (fuel.account, fuel.vat_code, fuel.coded_by) == ("Motor expenses", "S", "rule")
    fee = code_from_rules("NON-STERLING TRANSACTION FEE", rules, CHART)
    assert fee.account == "Bank charges" and fee.receipt_needed is False
    assert code_from_rules("NOWHERE LTD", rules, CHART) is None  # a rule pointing outside the chart is ignored
    assert CHART.code("Bank charges") == "6600"


def test_supplier_book_is_fuzzy_but_not_loose():
    book = SupplierBook(pd.DataFrame({"name": ["Severnvale Office Supplies Ltd", "Wrekinlink Telecom Ltd"]}))
    assert book.find("SEVERNVALE OFFICE SUPPLIES LIMITED")["name"] == "Severnvale Office Supplies Ltd"
    assert book.find("Severn Valley Tyres") is None


def test_supplier_vat_and_bank_checks():
    good_vat = make_gb_vat_number("2875316")
    supplier = {"name": "Acme", "vat_number": good_vat, "sort_code": "00-33-44", "account_number": "10027719"}
    doc = {"vat_total": 90.0, "currency": "GBP", "counterparty_vat_number": good_vat,
           "bank_sort_code": "009901", "bank_account_number": "99990001"}
    assert [c for c, _ in supplier_vat_checks(doc, supplier)] == ["bank_details_changed"]
    same_bank = dict(doc, bank_sort_code="003344", bank_account_number="10027719")
    assert supplier_vat_checks(same_bank, supplier) == []
    no_number = dict(same_bank, counterparty_vat_number="")
    assert [c for c, _ in supplier_vat_checks(no_number, {**supplier, "vat_number": ""})] == ["vat_without_number"]
    invalid = dict(same_bank, counterparty_vat_number=good_vat[:-1] + str((int(good_vat[-1]) + 3) % 10))
    assert "vat_number_invalid" in [c for c, _ in supplier_vat_checks(invalid, supplier)]
    no_vat_charged = dict(no_number, vat_total=0.0)
    assert supplier_vat_checks(no_vat_charged, {**supplier, "vat_number": ""}) == []

# ------------------------------------------------------------------- tables


def test_upload_routing_by_column_headings():
    card = b"Transaction Date,Card ending,Description,Amount (GBP)\n01/10/2026,4417,FUEL,60.00\n"
    bank = b"Date,Description,Amount,Balance\n01/10/2026,BACS ACME,-60.00,1000\n"
    suppliers = b"Supplier,VAT Number,Sort Code\nAcme,GB123,00-11-22\n"
    payroll = b"Employee Name,Gross Pay,Net Pay\nA,100,80\n"
    assert detect_role("c.csv", card, {}) == "card_statement"
    assert detect_role("b.csv", bank, {}) == "bank_statement"
    assert detect_role("s.csv", suppliers, {}) == "suppliers"
    assert detect_role("p.csv", payroll, {}) == "payroll"
    assert detect_role("x.csv", b"Colour,Size\nred,big\n", {}) is None


def test_load_table_money_in_out_columns_and_brackets():
    data = b"Date,Details,Money out,Money in\n01/10/2026,Rent,500.00,\n02/10/2026,Refund,,(12.50)\n03/10/2026,Fee,1.20,\n"
    df = load_table("bank.csv", data, table_spec("bank_statement"))
    assert df["amount"].tolist() == [-500.0, -12.5, -1.2]
    assert df["date"].iloc[0] == pd.Timestamp("2026-10-01")


def test_client_config_can_add_aliases():
    spec = table_spec("card_statement", {"tables": {"card_statement": {"aliases": {"amount": ["Spend"]}}}})
    df = load_table("c.csv", b"Date,Merchant,Spend,Card\n01/10/2026,X,9.99,4417\n", spec)
    assert df["amount"].iloc[0] == 9.99 and df["card_last4"].iloc[0] == "4417"

# ----------------------------------------------------------------- findings


def test_findings_are_configured_sorted_and_numbered():
    raw = [Finding("missing_receipt", subject="Alex", finding="x", date=pd.Timestamp("2026-10-09")),
           Finding("arithmetic", subject="Coalbrook", finding="y"),
           Finding("blocked_vat", subject="Cafe", finding="z")]
    config = {"checks": {"missing_receipt": {"needs_human_check": True, "severity": "high"},
                         "blocked_vat": {"enabled": False}}}
    out = finalise(raw, config)
    assert [(f.id, f.check_id) for f in out] == [("EX-01", "arithmetic"), ("EX-02", "missing_receipt")]
    assert out[1].needs_human_check and out[1].severity == "High" and out[1].letter == "cardholder"
    assert out[0].hold and out[0].action.startswith("Ask the supplier")
    frame = findings_frame(out)
    assert frame["Needs human check"].tolist() == ["Yes", "Yes"] and "Email drafted to" in frame

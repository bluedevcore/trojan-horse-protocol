"""Generate the synthetic sample data for the Bookkeeping Agent demo.

Everything here is invented: the company ("Demo Company Ltd", a small solder
manufacturer), suppliers, customers, amounts, VAT numbers and bank details.
Bank sort codes start 00- (not issued to any bank), phone numbers are Ofcom
drama numbers, email domains end .example. No real personal or company data.
Re-run to regenerate (the output is byte-for-byte reproducible):

    python clients/somerset-solders/sample_data/generate.py

October 2026 month end. Inbox: 19 documents (17 supplier invoices as PDF or
email, a second copy of one of them sent as a reminder, and a supplier
statement); despatches to invoice for October (6 customers, 10 lines); open
sales invoices exported from Xero (14 invoices from July to September); the
October bank statement (9 customer receipts); the purchase order log (6 POs);
and the supplier list, customer list and chart of accounts.

Deliberate problems planted for the agent to find (17 exceptions):
  1  Penhallow Assay Laboratories  invoice email says "we have moved our banking": bank details differ from the supplier list
  2  Coldharbour Industrial Gases  CIG-55190 total £483.60, but £365.50 + £73.10 VAT = £438.60
  3  Brackenford Reels & Spools    BRS-40877 dated 28 Sep 2026, before the October period
  4  Larkmoor Freight              LF-30917 sent again as a "copy invoice" reminder: duplicate, second copy not posted
  5  Harrowden Safety Supplies     mixed order (extractor filters, gloves, first aid kit, office chair): coding unclear
  6  Brenwick Lab Supplies         not on the supplier list (new supplier) ...
  7  Brenwick Lab Supplies         ... and its VAT number GB 618 7402 xx fails the HMRC check digits
  8  Fernbrook Calibration         annual service contract Oct 2026 - Sep 2027: prepayment to spread
  9  Combe Electrical Services     charges £60.48 VAT but shows no VAT number (not VAT registered on our list)
 10  Wellsbrook Manor Hotel        customer lunch coded to Entertainment: £36.00 VAT not reclaimable
 11  Kingsdown Circuits            needs a PO on every invoice; sales order SO-6107 has none (invoice held)
 12  Saltmarsh Marine Electronics  INV-3051 is 67 days overdue: final notice drafted for approval
 13  Ashwick Heating Supplies      INV-3094 marked "Disputed" (wrong alloy returned): left out of the chase letter
 14  Bank statement                £1,152.00 from Trelawney Controls matches no open invoice (unallocated)
 15  Harbourside Plumbers' Merch.  £1,500.00 part payment against INV-3091 (£2,914.20): balance still due
 16  Carrowdene Metals             CM-118377 adds a £450.00 tin surcharge: £12,050.00 net against PO-2611 for £11,600.00
 17  Hollowmere Chemicals          statement lists HC-7769 (£432.00), which was never received (PO-2619 still open)
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
INBOX = OUT / "inbox"
ROOT = OUT.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.bookkeeping.vat import make_gb_vat_number  # noqa: E402

COMPANY = "Demo Company Ltd"
COMPANY_ADDRESS = ["Unit 4, Example Trading Estate", "Bridgwater TA6 0XX"]
COMPANY_EMAIL = "accounts@demo-company.example"


def vat(seven: str) -> str:
    n = make_gb_vat_number(seven)
    return f"GB {n[2:5]} {n[5:9]} {n[9:]}"


# ------------------------------------------------------------------ suppliers
def _sup(name, ref, account, code, vat_number, sort, acct, terms, email, contact, phone, address):
    return dict(name=name, ref=ref, account=account, code=code, vat=vat_number, sort=sort, acct=acct, terms=terms,
                email=email, contact=contact, phone=phone, address=address)


S = {
    "carrowdene": _sup("Carrowdene Metals Ltd", "CARROW01", "Raw materials - metals", "S", vat("4821706"), "00-14-52",
                       "10230418", 30, "sales.ledger@carrowdene-metals.example", "Neil Abbott", "0117 496 0412",
                       ["Foundry Lane", "Avonmouth BS11 0XX"]),
    "kilnhurst": _sup("Kilnhurst Alloys Ltd", "KILNHU01", "Raw materials - metals", "S", vat("3390587"), "00-25-63",
                      "10241529", 30, "accounts@kilnhurst-alloys.example", "Sara Venn", "01632 960 381",
                      ["Unit 9, Kilnhurst Works", "Rotherham S60 0XX"]),
    "hollowmere": _sup("Hollowmere Chemicals Ltd", "HOLLOW01", "Flux and chemicals", "S", vat("5103274"), "00-36-74",
                       "10252630", 30, "accounts@hollowmere-chem.example", "Ruth Calloway", "01632 960 527",
                       ["Hollowmere Industrial Park", "Gloucester GL2 0XX"]),
    "brackenford": _sup("Brackenford Reels & Spools Ltd", "BRACKE01", "Packaging and spools", "S", vat("2768431"),
                        "00-47-85", "10263741", 30, "orders@brackenford-reels.example", "Tom Hensley", "01632 960 638",
                        ["Brackenford Mill", "Frome BA11 0XX"]),
    "coldharbour": _sup("Coldharbour Industrial Gases Ltd", "COLDHA01", "Industrial gases", "S", vat("6014298"),
                        "00-58-96", "10274852", 30, "accounts@coldharbour-gases.example", "Lee Morrish", "01632 960 749",
                        ["Coldharbour Road", "Bridgwater TA6 0XX"]),
    "southvane": _sup("Southvane Energy Ltd", "SOUTHV01", "Light, power and heat", "S", vat("7425816"), "00-69-17",
                      "10285963", 14, "business@southvane-energy.example", "", "01632 960 850",
                      ["PO Box 4XX", "Exeter EX2 0XX"]),
    "kestrelnet": _sup("Kestrelnet Communications Ltd", "KESTRE01", "Telephone and internet", "S", vat("3857120"),
                       "00-71-28", "10297074", 14, "billing@kestrelnet.example", "", "01632 960 961",
                       ["Kestrel House, Market Way", "Taunton TA1 0XX"]),
    "larkmoor": _sup("Larkmoor Freight Ltd", "LARKMO01", "Carriage outwards", "S", vat("4962035"), "00-82-39",
                     "10308185", 14, "credit.control@larkmoor-freight.example", "Shona Tilley", "01632 960 072",
                     ["Larkmoor Distribution Park", "Yeovil BA22 0XX"]),
    "penhallow": _sup("Penhallow Assay Laboratories Ltd", "PENHAL01", "Laboratory testing", "S", vat("2591746"),
                      "00-93-41", "10319296", 30, "accounts@penhallow-assay.example", "Imogen Hart", "01632 960 183",
                      ["2 Science Park Way", "Plymouth PL6 0XX"]),
    "fernbrook": _sup("Fernbrook Calibration Services Ltd", "FERNBR01", "Repairs and maintenance", "S", vat("6638203"),
                      "00-15-62", "10320307", 30, "service@fernbrook-cal.example", "Martin Doyle", "01632 960 294",
                      ["Fernbrook Business Centre", "Taunton TA2 0XX"]),
    "combe": _sup("Combe Electrical Services", "COMBEE01", "Repairs and maintenance", "O", "", "00-26-73", "10331418",
                  14, "gareth@combe-electrical.example", "Gareth Combe", "07700 900 382",
                  ["14 Orchard Rise", "Bridgwater TA7 0XX"]),
    "harrowden": _sup("Harrowden Safety Supplies Ltd", "HARROW01", "", "S", vat("5279314"), "00-37-84", "10342529", 30,
                      "sales@harrowden-safety.example", "Kelly Burge", "0117 496 0305",
                      ["Unit 3, Harrowden Court", "Bristol BS3 0XX"]),
    "stanchester": _sup("Stanchester Office Supplies Ltd", "STANCH01", "Printing and stationery", "S", vat("8146025"),
                        "00-48-95", "10353630", 30, "accounts@stanchester-office.example", "", "01632 960 416",
                        ["8 Stanchester Way", "Yeovil BA20 0XX"]),
    "kingsbury": _sup("Kingsbury Forklift Hire Ltd", "KINGSB01", "Plant and equipment hire", "S", vat("3702649"),
                      "00-59-06", "10364741", 30, "hire@kingsbury-forklifts.example", "", "01632 960 538",
                      ["Kingsbury Yard", "Wellington TA21 0XX"]),
    "holloway": _sup("Holloway Waste & Recycling Ltd", "HOLLOW02", "Waste disposal", "S", vat("4518377"), "00-61-17",
                     "10375852", 30, "accounts@holloway-waste.example", "Dean Pocock", "01632 960 649",
                     ["Transfer Station, Holloway Lane", "Bridgwater TA5 0XX"]),
    "wellsbrook": _sup("Wellsbrook Manor Hotel Ltd", "WELLSB01", "Entertainment", "S", vat("6873051"), "00-72-28",
                       "10386963", 30, "events@wellsbrook-manor.example", "Hannah Royle", "01632 960 750",
                       ["Wellsbrook Lane", "Cheddar BS27 0XX"]),
    "rowan": _sup("Rowan & Pike Chartered Accountants", "ROWANP01", "Accountancy fees", "S", vat("2930485"), "00-83-39",
                  "10397074", 14, "office@rowanpike.example", "Joanna Pike", "01632 960 861",
                  ["4 Market Walk", "Taunton TA1 0XX"]),
}
BRENWICK = _sup("Brenwick Lab Supplies Ltd", "", "", "S", vat("6187402"), "00-94-51", "10408185", 30,
                "sales@brenwick-lab.example", "", "01632 960 972", ["Unit 12, Brenwick Trade Park", "Swindon SN2 0XX"])
BRENWICK["vat"] = BRENWICK["vat"][:-2] + f"{(int(BRENWICK['vat'][-2:]) + 3) % 100:02d}"  # wrong check digits

# ---------------------------------------------------------------------- PDFs

FONTS = {"title": ("Helvetica-Bold", 18), "big": ("Helvetica-Bold", 13), "h": ("Helvetica-Bold", 11),
         "b": ("Helvetica-Bold", 9.5), "n": ("Helvetica", 9.5), "s": ("Helvetica", 8), "i": ("Helvetica-Oblique", 9.5)}
# Item tables: description | qty | unit price | VAT | net. Statement tables: date | ref | details | amount.
ITEM_COLS = [(0.0, "l"), (0.70, "r"), (0.81, "r"), (0.88, "r"), (1.0, "r")]
STATEMENT_COLS = [(0.0, "l"), (0.17, "l"), (0.36, "l"), (1.0, "r")]


def _pdf(lines: list[tuple], *, size=(595, 842), margin=50) -> bytes:
    """Tiny layout engine: (style, text) lines top to bottom, or (style, [cells], cols) for table rows.

    Raises if a left-aligned cell would run into the next column, so every PDF reads cleanly.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, invariant=1)  # reproducible bytes
    width, height = size
    usable = width - 2 * margin
    y = height - margin
    for line in lines:
        style = line[0]
        if style == "gap":
            y -= 8
            continue
        if style == "rule":
            c.setStrokeColorRGB(0.75, 0.78, 0.82)
            c.line(margin, y + 4, width - margin, y + 4)
            y -= 6
            continue
        font, sz = FONTS[style]
        c.setFont(font, sz)
        if isinstance(line[1], str):
            if stringWidth(line[1], font, sz) > usable:
                raise ValueError(f"Line too long for the page: {line[1]!r}")
            c.drawString(margin, y, line[1])
        else:
            cells, cols = line[1], line[2]
            for i, (cell, (pos, align)) in enumerate(zip(cells, cols)):
                x = margin + usable * pos
                if align == "l":
                    room = usable * (cols[i + 1][0] - pos) - 8 if i + 1 < len(cols) else usable - usable * pos
                    if i + 1 < len(cols) and cols[i + 1][1] == "r":
                        room -= stringWidth(cells[i + 1], font, sz) if i + 1 < len(cells) else 0
                    if stringWidth(cell, font, sz) > room:
                        raise ValueError(f"Cell too wide for its column: {cell!r}")
                    c.drawString(x, y, cell)
                else:
                    c.drawRightString(x, y, cell)
        y -= sz + 5
    c.showPage()
    c.save()
    return buf.getvalue()


def money(v: float) -> str:
    return f"£{v:,.2f}"


def invoice_pdf(sup: dict, *, number: str, date: str, due: str | None, items: list[tuple], title: str = "INVOICE",
                total: float | None = None, extra: list[str] = (), bank: tuple[str, str] | None = None,
                vat_number: str | None = None, terms: str = "", po: str = "", account: str = "DEMO01") -> bytes:
    """items: (description, qty, unit price, VAT rate); net per line = qty x unit price."""
    rows = [(desc, qty, unit, round(qty * unit, 2), rate) for desc, qty, unit, rate in items]
    by_rate: dict[float, float] = {}
    for *_, net, rate in rows:
        by_rate[rate] = round(by_rate.get(rate, 0.0) + net, 2)
    vat_summary = [(rate, net, round(net * rate / 100, 2)) for rate, net in sorted(by_rate.items(), reverse=True)]
    net_total = round(sum(r[3] for r in rows), 2)
    vat_total = round(sum(v[2] for v in vat_summary), 2)
    total = round(net_total + vat_total, 2) if total is None else total
    vn = sup.get("vat", "") if vat_number is None else vat_number
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]] + [("n", f"Tel {sup['phone']} · {sup['email']}")]
    if vn:
        lines.append(("n", f"VAT Reg No: {vn}"))
    word = "Credit note" if "CREDIT" in title else "Invoice"
    lines += [("gap",), ("title", title), ("gap",), ("n", f"{word} number: {number}"), ("n", f"{word} date: {date}")]
    if due:
        lines.append(("n", f"Due date: {due}"))
    if po:
        lines.append(("n", f"Your order ref: {po}"))
    lines.append(("n", f"Customer account: {account}"))
    lines += [("gap",), ("b", "Invoice to:"), ("n", COMPANY)] + [("n", a) for a in COMPANY_ADDRESS] + [("gap",)]
    lines += [("b", ["Description", "Qty", "Unit price", "VAT", "Net"], ITEM_COLS), ("rule",)]
    for desc, qty, unit, net, rate in rows:
        unit_text = f"£{unit:,.5f}".rstrip("0").rstrip(".") if round(unit, 2) != unit else money(unit)
        lines.append(("n", [desc, f"{qty:,g}", unit_text, f"{rate:g}%", money(net)], ITEM_COLS))
    lines += [("rule",), ("n", ["Subtotal (net)", "", "", "", money(net_total)], ITEM_COLS)]
    for rate, vnet, vvat in vat_summary:
        lines.append(("n", [f"VAT @ {rate:g}% on {money(vnet)}", "", "", "", money(vvat)], ITEM_COLS))
    lines += [("b", ["Total credit" if word == "Credit note" else "Total due", "", "", "", money(total)], ITEM_COLS), ("gap",)]
    if terms:
        lines.append(("n", terms))
    if bank:
        lines.append(("n", f"Pay by bank transfer to {sup['name']}: sort code {bank[0]}, account number {bank[1]}."))
        lines.append(("n", f"Please quote {number} as the payment reference."))
    lines += [("s", e) for e in extra]
    return _pdf(lines)


def statement_pdf(sup: dict, *, date: str, account: str, brought_forward: tuple[str, float],
                  rows: list[tuple[str, str, str, float]], bank: tuple[str, str]) -> bytes:
    """rows: (date, reference, details, amount); payments negative."""
    balance = round(brought_forward[1] + sum(r[3] for r in rows), 2)
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]] + [("n", f"Tel {sup['phone']} · {sup['email']}")]
    lines += [("n", f"VAT Reg No: {sup['vat']}"), ("gap",), ("title", "STATEMENT OF ACCOUNT"), ("gap",),
              ("n", f"Statement date: {date}"), ("n", f"Customer account: {account}"), ("gap",),
              ("b", "Account holder:"), ("n", COMPANY)] + [("n", a) for a in COMPANY_ADDRESS] + [("gap",)]
    lines += [("i", f"Balance brought forward at {brought_forward[0]}: {money(brought_forward[1])}"), ("gap",)]
    lines += [("b", ["Date", "Reference", "Details", "Amount"], STATEMENT_COLS), ("rule",)]
    for d, ref, details, amount in rows:
        amount_text = f"-{money(-amount)}" if amount < 0 else money(amount)
        lines.append(("n", [d, ref, details, amount_text], STATEMENT_COLS))
    lines += [("rule",), ("b", ["", "", "Balance due", money(balance)], STATEMENT_COLS), ("gap",),
              ("n", "Invoices are due 30 days from the invoice date. Please tell us within 14 days of any query."),
              ("n", f"Bank: sort code {bank[0]}, account number {bank[1]}. Please quote your account number.")]
    return _pdf(lines)

# --------------------------------------------------------------------- emails


def eml(*, sender: str, subject: str, date: str, body: str, attachment: tuple[str, bytes] | None = None,
        to: str = COMPANY_EMAIL) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(pd.Timestamp(date).tz_localize("Europe/London").to_pydatetime())
    msg["Message-ID"] = f"<{hashlib.sha1((subject + date).encode()).hexdigest()[:16]}@mail.example>"
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
        msg.set_boundary("==demo-" + hashlib.sha1(subject.encode()).hexdigest()[:20])  # reproducible bytes
    return bytes(msg)


def _bank(key: str) -> tuple[str, str]:
    return S[key]["sort"], S[key]["acct"]

# ------------------------------------------------------------------ documents


def supplier_documents() -> dict[str, bytes]:
    docs: dict[str, bytes] = {}

    # Brackenford: dated in September (prior period), on PO-2598
    docs["2026-09-28_brackenford_BRS-40877.pdf"] = invoice_pdf(
        S["brackenford"], number="BRS-40877", date="28/09/2026", due="28/10/2026", po="PO-2598",
        items=[("500g black ABS spools, box of 200", 6, 86.00, 20), ("250g black ABS spools, box of 300", 3, 74.50, 20),
               ("Printed reel labels, roll of 1,000", 4, 18.75, 20)],
        bank=_bank("brackenford"), terms="Terms: 30 days net. Goods remain our property until paid for.")

    # Fernbrook: annual contract paid up front (prepayment)
    docs["2026-10-01_fernbrook_FCS-2210.pdf"] = invoice_pdf(
        S["fernbrook"], number="FCS-2210", date="01/10/2026", due="31/10/2026",
        items=[("Annual service and calibration contract", 1, 2160.00, 20)], bank=_bank("fernbrook"),
        terms="Contract period: 01/10/2026 to 30/09/2027, invoiced annually in advance.",
        extra=["Covers the XRF alloy analyser, three melting-pot temperature controllers and the wire-drawing line gauges."])

    docs["2026-10-01_kingsbury_KFH-90214.pdf"] = invoice_pdf(
        S["kingsbury"], number="KFH-90214", date="01/10/2026", due="31/10/2026",
        items=[("Electric forklift 1.6t, contract hire - October 2026", 1, 165.00, 20)], bank=_bank("kingsbury"),
        terms="Hire agreement KF-2231. Monthly in advance.")

    docs["2026-10-02_kestrelnet_KN-560114.pdf"] = invoice_pdf(
        S["kestrelnet"], number="KN-560114", date="02/10/2026", due="16/10/2026",
        items=[("Leased line 100 Mbps - October 2026", 1, 145.00, 20), ("Hosted phone system, per user", 8, 11.50, 20),
               ("Call charges - September 2026", 1, 6.84, 20)],
        terms="Paid by Direct Debit on or after 16/10/2026. No action needed.")

    # Hollowmere: invoice by email, on PO-2617
    hc = invoice_pdf(
        S["hollowmere"], number="HC-7741", date="02/10/2026", due="01/11/2026", po="PO-2617",
        items=[("Water-white gum rosin, 25 kg sack", 8, 68.00, 20), ("Adipic acid activator, 5 kg tub", 4, 42.50, 20),
               ("Isopropyl alcohol 99.9%, 25 litre drum", 6, 61.00, 20), ("Hazardous goods delivery", 1, 45.00, 20)],
        bank=_bank("hollowmere"), terms="Terms: 30 days net.")
    docs["2026-10-02_hollowmere_HC-7741.eml"] = eml(
        sender=f"{S['hollowmere']['contact']} <{S['hollowmere']['email']}>", subject="Invoice HC-7741 - your order PO-2617",
        date="2026-10-02 15:20", attachment=("HC-7741.pdf", hc),
        body="Good afternoon,\n\nPlease find attached invoice HC-7741 for the rosin, activator and isopropyl alcohol "
             "delivered today against your order PO-2617.\n\nKind regards,\nRuth Calloway\nAccounts, Hollowmere Chemicals Ltd")

    # Carrowdene: silver on PO-2614 (matches), tin on PO-2611 with a surcharge the PO doesn't cover
    docs["2026-10-05_carrowdene_CM-118204.pdf"] = invoice_pdf(
        S["carrowdene"], number="CM-118204", date="05/10/2026", due="04/11/2026", po="PO-2614",
        items=[("Fine silver grain 99.99%, per kg", 6, 860.00, 20), ("Assay certificate", 1, 35.00, 20)],
        bank=_bank("carrowdene"), terms="Terms: 30 days net. Metal prices fixed on the order date.")
    docs["2026-10-12_carrowdene_CM-118377.pdf"] = invoice_pdf(
        S["carrowdene"], number="CM-118377", date="12/10/2026", due="11/11/2026", po="PO-2611",
        items=[("Tin ingot Sn 99.95%, per kg (delivered)", 500, 23.20, 20),
               ("Tin market surcharge since order date, per kg", 500, 0.90, 20)],
        bank=_bank("carrowdene"), terms="Terms: 30 days net.")

    # Larkmoor: mixed-rate freight (UK 20%, export 0%), then a copy sent as a reminder (duplicate)
    lf = invoice_pdf(
        S["larkmoor"], number="LF-30917", date="07/10/2026", due="21/10/2026",
        items=[("UK pallet deliveries, 1-6 October", 12, 48.00, 20),
               ("Export consignment to Cork, Ireland, 3 Oct (2 pallets)", 1, 310.00, 0),
               ("Export consignment to Eindhoven, NL, 6 Oct (1 pallet)", 1, 385.00, 0)],
        bank=_bank("larkmoor"), terms="Terms: 14 days. International transport of exported goods is zero-rated.")
    docs["2026-10-07_larkmoor_LF-30917.pdf"] = lf
    docs["2026-10-28_larkmoor_copy-invoice-LF-30917.eml"] = eml(
        sender=f"{S['larkmoor']['contact']} <{S['larkmoor']['email']}>", subject="Copy invoice LF-30917 - now overdue",
        date="2026-10-28 10:05", attachment=("LF-30917.pdf", lf),
        body="Hello,\n\nOur records show that invoice LF-30917, dated 7 October for £1,386.20, was due on 21 October "
             "and is still unpaid. A copy is attached. Could you let me know when payment will be made?\n\n"
             "Thanks,\nShona Tilley\nCredit Control, Larkmoor Freight Ltd")

    docs["2026-10-09_southvane_SV-8812046.pdf"] = invoice_pdf(
        S["southvane"], number="SV-8812046", date="09/10/2026", due="23/10/2026",
        items=[("Day units, kWh", 18420, 0.2184, 20), ("Night units, kWh", 6150, 0.1462, 20),
               ("Standing charge, days", 30, 2.15, 20), ("Capacity charge, days", 30, 1.80, 20),
               ("Climate Change Levy, kWh", 24570, 0.00775, 20)],
        terms="Supply period 01/09/2026 to 30/09/2026. Paid by Direct Debit on or after 23/10/2026.",
        extra=["Supply address: Unit 4, Example Trading Estate. Meter 2200 0418 7731."])

    # Penhallow: invoice arrives with an email about "new bank details" (fraud pattern)
    pal = invoice_pdf(
        S["penhallow"], number="PAL-6620", date="13/10/2026", due="12/11/2026",
        items=[("Alloy analysis (ICP-OES), SAC305 batch certificate", 8, 38.00, 20),
               ("RoHS lead screening, per batch", 8, 12.50, 20)],
        bank=("00-99-07", "99990417"), terms="Terms: 30 days net.")
    docs["2026-10-13_penhallow_PAL-6620.eml"] = eml(
        sender="Penhallow Accounts <penhallow.accounts@mailbox.example>", subject="Invoice PAL-6620 - updated bank details",
        date="2026-10-13 17:52", attachment=("PAL-6620.pdf", pal),
        body="Dear Accounts,\n\nPlease find attached invoice PAL-6620 for October's assay work.\n\nPlease note that we "
             "have moved our banking. Please update your records and pay this and all future invoices to the new account "
             "shown on the invoice.\n\nKind regards,\nAccounts Department\nPenhallow Assay Laboratories Ltd")

    # Coldharbour: printed total doesn't add up (£438.60 printed as £483.60)
    docs["2026-10-14_coldharbour_CIG-55190.pdf"] = invoice_pdf(
        S["coldharbour"], number="CIG-55190", date="14/10/2026", due="13/11/2026", total=483.60,
        items=[("Oxygen-free nitrogen, size W cylinder refill", 10, 28.40, 20),
               ("Cylinder rental - October, per cylinder", 14, 4.25, 20), ("Delivery charge", 1, 22.00, 20)],
        bank=_bank("coldharbour"), terms="Terms: 30 days net. Cylinder account CA-0571.")

    docs["2026-10-16_wellsbrook_WMH-20418.pdf"] = invoice_pdf(
        S["wellsbrook"], number="WMH-20418", date="16/10/2026", due="15/11/2026",
        items=[("Business lunch for 6 guests, 15 October 2026", 1, 150.00, 20), ("Private dining room hire", 1, 30.00, 20)],
        bank=_bank("wellsbrook"), terms="Booking reference WM-3318: customer visit (Vantage Board Assembly).")

    # Combe Electrical: VAT charged, no VAT number on the invoice or our supplier list
    docs["2026-10-19_combe-electrical_0347.pdf"] = invoice_pdf(
        S["combe"], number="0347", date="19/10/2026", due="02/11/2026", vat_number="",
        items=[("Fault-find and repair, melting pot 2: labour (hours)", 4.5, 48.00, 20),
               ("Parts: 40A contactor, thermocouple lead, terminals", 1, 86.40, 20)],
        bank=_bank("combe"), terms="Thank you for your business. Gareth Combe, trading as Combe Electrical Services.")

    # Harrowden: mixed order, no default account on the supplier list
    docs["2026-10-21_harrowden_HSS-22871.pdf"] = invoice_pdf(
        S["harrowden"], number="HSS-22871", date="21/10/2026", due="20/11/2026",
        items=[("Fume extractor carbon and HEPA filter set", 4, 46.50, 20), ("Nitrile gloves, box of 100", 10, 6.80, 20),
               ("First aid kit refill, large workplace", 1, 39.95, 20), ("Ergonomic task chair with arms", 1, 289.00, 20)],
        bank=_bank("harrowden"), terms="Terms: 30 days net.")

    # Brenwick: new supplier, VAT number fails the check digits
    docs["2026-10-22_brenwick_BLS-1043.pdf"] = invoice_pdf(
        BRENWICK, number="BLS-1043", date="22/10/2026", due="21/11/2026",
        items=[("Clay-graphite crucible, size 20", 2, 94.00, 20), ("Type K thermocouple probe, 300 mm", 4, 27.50, 20),
               ("Crucible tongs, 600 mm", 1, 42.00, 20)],
        bank=(BRENWICK["sort"], BRENWICK["acct"]), terms="New account - welcome! 30 days from invoice.")

    docs["2026-10-23_stanchester_STN-55102.pdf"] = invoice_pdf(
        S["stanchester"], number="STN-55102", date="23/10/2026", due="22/11/2026",
        items=[("A4 copier paper 80gsm, box of 5 reams", 4, 23.60, 20), ("Black toner cartridge", 2, 42.00, 20),
               ("Despatch labels, 2-up, box of 1,000", 3, 14.90, 20)],
        bank=_bank("stanchester"), terms="Terms: 30 days net.")

    docs["2026-10-30_holloway_HWR-7781.pdf"] = invoice_pdf(
        S["holloway"], number="HWR-7781", date="30/10/2026", due="29/11/2026",
        items=[("Hazardous waste: flux residues, 205 litre drum", 2, 96.00, 20),
               ("Hazardous waste consignment note", 1, 15.00, 20), ("General waste 1100L bin, per lift", 4, 21.50, 20)],
        bank=_bank("holloway"), terms="Terms: 30 days net. Consignment note HW-2026-0418 on file.")

    # Hollowmere statement: lists HC-7769, which never arrived
    docs["2026-10-31_hollowmere_statement.pdf"] = statement_pdf(
        S["hollowmere"], date="31/10/2026", account="DEMO01", brought_forward=("30/09/2026", 1240.80),
        rows=[("02/10/2026", "HC-7741", "Invoice", 1350.00), ("16/10/2026", "HC-7769", "Invoice", 432.00),
              ("20/10/2026", "HC-7702", "Payment received, thank you", -1240.80)],
        bank=_bank("hollowmere"))
    return docs

# ---------------------------------------------------------------- spreadsheets


CUSTOMERS = [  # name, ref, email, contact, terms, PO required, credit limit
    ("Vantage Board Assembly Ltd", "VANTAG01", "purchase.ledger@vantage-board.example", "Priya Khanna", 30, "Yes", 25000),
    ("Kingsdown Circuits Ltd", "KINGSD01", "accounts.payable@kingsdown-circuits.example", "Rob Ellery", 30, "Yes", 20000),
    ("Ballykeel Electronics Ltd", "BALLYK01", "accounts@ballykeel-electronics.example", "Siobhan Duggan", 45, "No", 15000),
    ("Verhoeven Elektronica B.V.", "VERHOE01", "crediteuren@verhoeven-elektronica.example", "Daan de Vries", 30, "Yes", 15000),
    ("Harbourside Plumbers' Merchants Ltd", "HARBOU01", "accounts@harbourside-pm.example", "Colin Marsh", 30, "No", 8000),
    ("Tidewell Controls Ltd", "TIDEWE01", "payables@tidewell-controls.example", "Anita Shaw", 30, "Yes", 10000),
    ("Saltmarsh Marine Electronics Ltd", "SALTMA01", "accounts@saltmarsh-marine.example", "Gavin Treloar", 30, "No", 5000),
    ("Ashwick Heating Supplies Ltd", "ASHWIC01", "purchase.ledger@ashwick-heating.example", "Debbie Lane", 30, "No", 3000),
    ("Penrose Audio Ltd", "PENROS01", "accounts@penrose-audio.example", "Ollie Grant", 30, "No", 2000),
]


def customers_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Customer": n, "Account Ref": r, "Email": e, "Contact": c, "Terms (days)": t, "PO Required": p,
                          "Credit Limit": l} for n, r, e, c, t, p, l in CUSTOMERS])


def suppliers_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Supplier": s["name"], "Account Ref": s["ref"], "Default Account": s["account"],
                          "Default VAT": s["code"], "VAT Number": s["vat"], "Sort Code": s["sort"],
                          "Account Number": s["acct"], "Terms (days)": s["terms"], "Email": s["email"],
                          "Contact": s["contact"]} for s in S.values()])


WIRE07 = ("SAC-W07-500", "SAC305 lead-free solder wire 0.7mm, 500g reel", 68.50)
WIRE10 = ("SAC-W10-500", "SAC305 lead-free solder wire 1.0mm, 500g reel", 64.00)
FLUX = ("FLX-NC20-5L", "NC-20 no-clean liquid flux, 5 litre", 58.00)
SAC_BAR = ("SAC-BAR-1KG", "SAC305 solder bar, 1kg", 64.00)
SNCU_BAR = ("SNCU-BAR-1KG", "Sn99.3Cu0.7 solder bar, 1kg", 31.20)
PLUMB = ("PLM-W30-500", "Plumbing solder wire Sn97Cu3 3mm, 500g reel", 16.40)
PASTE = ("PLM-FLXP-250", "Plumbing flux paste, 250g tub", 4.10)


def despatches() -> pd.DataFrame:
    rows = [("06/10/2026", "DN-8841", "Vantage Board Assembly Ltd", "SO-6102", "VBA-PO-44120", WIRE07, 90, "S"),
            ("06/10/2026", "DN-8841", "Vantage Board Assembly Ltd", "SO-6102", "VBA-PO-44120", FLUX, 16, "S"),
            ("09/10/2026", "DN-8850", "Kingsdown Circuits Ltd", "SO-6107", "", SAC_BAR, 120, "S"),  # planted: no PO
            ("13/10/2026", "DN-8857", "Ballykeel Electronics Ltd", "SO-6110", "BE-7731", WIRE10, 80, "Z"),
            ("13/10/2026", "DN-8857", "Ballykeel Electronics Ltd", "SO-6110", "BE-7731", FLUX, 12, "Z"),
            ("16/10/2026", "DN-8863", "Verhoeven Elektronica B.V.", "SO-6114", "VE-2026-0381", SNCU_BAR, 200, "Z"),
            ("21/10/2026", "DN-8871", "Harbourside Plumbers' Merchants Ltd", "SO-6116", "", PLUMB, 220, "S"),
            ("21/10/2026", "DN-8871", "Harbourside Plumbers' Merchants Ltd", "SO-6116", "", PASTE, 300, "S"),
            ("27/10/2026", "DN-8879", "Tidewell Controls Ltd", "SO-6119", "TC-10872", WIRE07, 36, "S"),
            ("27/10/2026", "DN-8879", "Tidewell Controls Ltd", "SO-6119", "TC-10872", SNCU_BAR, 80, "S")]
    return pd.DataFrame([{"Despatch Date": d, "Despatch Note": dn, "Customer": c, "Sales Order": so, "Customer PO": po,
                          "Item Code": item[0], "Description": item[1], "Qty": q, "Unit Price": item[2], "VAT Code": v}
                         for d, dn, c, so, po, item, q, v in rows])


def open_invoices() -> pd.DataFrame:
    rows = [("Saltmarsh Marine Electronics Ltd", "INV-3051", "31/07/2026", "30/08/2026", "", 1846.80,
             "Reminder sent 15/09/2026; no reply"),  # planted: final notice
            ("Vantage Board Assembly Ltd", "INV-3088", "31/08/2026", "30/09/2026", "VBA-PO-43871", 6012.00, ""),
            ("Harbourside Plumbers' Merchants Ltd", "INV-3091", "31/08/2026", "30/09/2026", "", 2914.20, ""),
            ("Ashwick Heating Supplies Ltd", "INV-3094", "31/08/2026", "30/09/2026", "", 1226.40,
             "Disputed: 6 reels returned as wrong alloy, credit requested"),  # planted: dispute
            ("Ballykeel Electronics Ltd", "INV-3097", "31/08/2026", "15/10/2026", "BE-7652", 4980.00, ""),
            ("Penrose Audio Ltd", "INV-3112", "30/09/2026", "30/10/2026", "", 684.00, ""),
            ("Vantage Board Assembly Ltd", "INV-3118", "30/09/2026", "30/10/2026", "VBA-PO-44016", 5436.00, ""),
            ("Kingsdown Circuits Ltd", "INV-3121", "30/09/2026", "30/10/2026", "KC-5530", 7128.00, ""),
            ("Tidewell Controls Ltd", "INV-3124", "30/09/2026", "30/10/2026", "TC-10790", 2887.20, ""),
            ("Verhoeven Elektronica B.V.", "INV-3127", "30/09/2026", "30/10/2026", "VE-2026-0344", 5904.00, ""),
            ("Harbourside Plumbers' Merchants Ltd", "INV-3130", "30/09/2026", "30/10/2026", "", 3102.00, ""),
            ("Saltmarsh Marine Electronics Ltd", "INV-3133", "30/09/2026", "30/10/2026", "", 1254.00, ""),
            ("Ballykeel Electronics Ltd", "INV-3136", "30/09/2026", "14/11/2026", "BE-7718", 5212.00, ""),
            ("Ashwick Heating Supplies Ltd", "INV-3140", "30/09/2026", "30/10/2026", "", 948.00, "")]
    return pd.DataFrame([{"Contact": c, "Invoice Number": n, "Invoice Date": d, "Due Date": due, "Customer PO": po,
                          "Invoice Total": f"{amt:.2f}", "Paid": "0.00", "Notes": note} for c, n, d, due, po, amt, note in rows])


def bank_statement() -> pd.DataFrame:
    rows = [("01/10/2026", "DD SOUTHVANE ENERGY", "SV-8790311", 5412.36, None),
            ("02/10/2026", "BACS CARROWDENE METALS LTD", "DEMO CO SEPT", 13212.00, None),
            ("06/10/2026", "FASTER PAYMENT PENROSE AUDIO LTD", "INV-3112", None, 684.00),
            ("15/10/2026", "BACS BALLYKEEL ELECTRONICS", "INV-3097", None, 4980.00),
            ("16/10/2026", "DD KESTRELNET COMMS", "KN-555902", 289.13, None),
            ("20/10/2026", "BACS HARBOURSIDE PLUMBERS", "INV-3091 PART", None, 1500.00),  # planted: part payment
            ("20/10/2026", "BACS HOLLOWMERE CHEMICALS", "HC-7702", 1240.80, None),
            ("22/10/2026", "BACS TRELAWNEY CONTROLS LTD", "TC PAYMENT", None, 1152.00),  # planted: unallocated
            ("22/10/2026", "HMRC PAYE NI", "PAYE OCT 26", 9840.27, None),
            ("27/10/2026", "INTL PAYMENT VERHOEVEN ELEKTRONICA BV", "PAYMENT SEPT", None, 5904.00),  # no invoice ref
            ("28/10/2026", "BACS TIDEWELL CONTROLS", "INV-3124", None, 2887.20),
            ("28/10/2026", "SALARIES OCTOBER", "PAYROLL", 38465.20, None),
            ("29/10/2026", "BACS VANTAGE BOARD ASSY", "INV-3088", None, 6012.00),
            ("30/10/2026", "BACS KINGSDOWN CIRCUITS", "INV-3121", None, 7128.00),
            ("30/10/2026", "BACS VANTAGE BOARD ASSY", "INV-3118", None, 5436.00),
            ("30/10/2026", "BANK CHARGES", "SEPT CHARGES", 18.50, None)]
    balance, out = 64210.45, []
    for d, desc, ref, money_out, money_in in rows:
        balance = round(balance - (money_out or 0) + (money_in or 0), 2)
        out.append({"Date": d, "Description": desc, "Reference": ref,
                    "Money Out": f"{money_out:.2f}" if money_out else "", "Money In": f"{money_in:.2f}" if money_in else "",
                    "Balance": f"{balance:.2f}"})
    return pd.DataFrame(out)


def purchase_orders() -> pd.DataFrame:
    rows = [("PO-2598", "15/09/2026", "Brackenford Reels & Spools Ltd", "Spools and reel labels", 814.50, "Delivered"),
            ("PO-2611", "01/10/2026", "Carrowdene Metals Ltd", "Tin ingot Sn 99.95%, 500 kg @ £23.20 delivered", 11600.00, "Delivered"),
            ("PO-2614", "02/10/2026", "Carrowdene Metals Ltd", "Fine silver grain, 6 kg @ £860.00 + assay certificate", 5195.00, "Delivered"),
            ("PO-2617", "01/10/2026", "Hollowmere Chemicals Ltd", "Rosin, activator, isopropyl alcohol + delivery", 1125.00, "Delivered"),
            ("PO-2619", "12/10/2026", "Hollowmere Chemicals Ltd", "Adipic acid activator, 5 kg tub x 8", 360.00, "Delivered"),
            ("PO-2620", "20/10/2026", "Kilnhurst Alloys Ltd", "Copper shot, 25 kg", 412.50, "Ordered")]
    return pd.DataFrame([{"PO Number": n, "Date": d, "Supplier": s, "Description": desc, "Net Amount": f"{amt:.2f}", "Status": st}
                         for n, d, s, desc, amt, st in rows])


def chart_csv() -> pd.DataFrame:
    rows = [("200", "Sales", "Revenue", "Sales of solder, flux and related products"),
            ("260", "Other revenue", "Revenue", ""),
            ("300", "Raw materials - metals", "Direct costs", "Tin, silver, copper and other metals for alloying"),
            ("305", "Flux and chemicals", "Direct costs", "Rosin, activators, solvents and other flux ingredients"),
            ("310", "Packaging and spools", "Direct costs", "Spools, reels, labels and cartons for finished goods"),
            ("315", "Industrial gases", "Direct costs", "Nitrogen and argon, cylinder rental"),
            ("320", "Production consumables", "Direct costs",
             "Crucibles, thermocouples, extraction filters and other items used up in production"),
            ("325", "Carriage outwards", "Direct costs", "Deliveries to customers, including export freight"),
            ("330", "Laboratory testing", "Direct costs", "Alloy assays and test certificates"),
            ("404", "Bank fees", "Expense", "Bank charges"),
            ("412", "Accountancy fees", "Expense", "Accountants and payroll bureau"),
            ("420", "Entertainment", "Expense", "Customer hospitality (VAT not reclaimable)"),
            ("429", "General expenses", "Expense", "Small items that fit nowhere else"),
            ("433", "Insurance", "Expense", ""),
            ("445", "Light, power and heat", "Expense", "Electricity and gas, including the melting pots"),
            ("461", "Printing and stationery", "Expense", "Paper, toner, labels and office supplies"),
            ("468", "Health and safety", "Expense", "PPE, gloves, first aid and safety equipment"),
            ("473", "Repairs and maintenance", "Expense", "Machinery repairs, electrical work, service and calibration contracts"),
            ("476", "Plant and equipment hire", "Expense", "Forklift and equipment hire"),
            ("477", "Wages and salaries", "Payroll", ""),
            ("485", "Subscriptions", "Expense", "Software and memberships"),
            ("489", "Telephone and internet", "Expense", ""),
            ("493", "Travel", "Expense", ""),
            ("495", "Waste disposal", "Expense", "General and hazardous waste collection"),
            ("620", "Prepayments", "Current asset", ""),
            ("710", "Office equipment", "Fixed asset", "Furniture and equipment over £250 kept for more than a year"),
            ("820", "VAT", "Current liability", ""),
            ("9999", "Suspense", "Suspense", "Use only when the right account is genuinely unclear")]
    return pd.DataFrame(rows, columns=["Account Code", "Account Name", "Account Type", "Notes"])

# --------------------------------------------------------------------- main


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()
    docs = supplier_documents()
    for name, data in docs.items():
        (INBOX / name).write_bytes(data)
    open_invoices().to_csv(OUT / "open_sales_invoices_31-oct-2026.csv", index=False)
    bank_statement().to_csv(OUT / "bank_statement_oct-2026.csv", index=False)
    purchase_orders().to_csv(OUT / "purchase_orders_log.csv", index=False)
    suppliers_csv().to_csv(OUT / "supplier_list.csv", index=False)
    customers_csv().to_csv(OUT / "customer_list.csv", index=False)
    chart_csv().to_csv(OUT / "chart_of_accounts.csv", index=False)
    with pd.ExcelWriter(OUT / "despatches_to_invoice_oct-2026.xlsx", engine="xlsxwriter") as writer:
        despatches().to_excel(writer, index=False, sheet_name="October despatches")
        writer.book.set_properties({"created": datetime(2026, 11, 1, 9, 0)})  # reproducible bytes
    print(f"Wrote {len(docs)} documents to {INBOX} and 7 spreadsheets to {OUT}")
    print("Brenwick VAT number (invalid on purpose):", BRENWICK["vat"])


if __name__ == "__main__":
    main()

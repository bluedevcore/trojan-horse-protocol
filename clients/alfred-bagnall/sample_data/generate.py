"""Generate the synthetic sample data for the Debtor & Filing Agent demo.

Everything here is invented: the contractor ("Demo Decorating Contractors Ltd",
Erith branch), its customers, projects, sites, people, invoice numbers and
amounts. Postcodes end 0XX, phone numbers are Ofcom drama numbers, email
domains end .example, the bank statement has no account details. No real
personal or company data. Re-run to regenerate (byte-for-byte the same):

    python clients/alfred-bagnall/sample_data/generate.py

The branch of a painting, decorating and building maintenance contractor, as
at 5 November 2026:

  sales_ledger_open_invoices.xlsx  26 open items for 10 customers (Jul-Oct 2026),
                                   as kept in the branch's Excel sales ledger
  bank_statement_oct-2026.csv      1 Oct - 4 Nov 2026: 7 customer receipts and
                                   12 payments out (the agent only uses money in)
  customer_list.csv                10 customers: accounts contact, email, terms, credit limit
  project_register.csv             11 live projects (job numbers J-41xx) with site and keywords
  inbox/                           24 documents waiting to be filed: contracts, customer
                                   orders, variation instructions, site minutes, remittance
                                   advices and correspondence (PDF and .eml), plus one photo

Debtors: what the agent should work out
  - 5 invoices are cleared by money on the bank statement: by invoice number
    (Kestrelgate SI-30364, Riverholt SI-30341, Saltings SI-30377 + SI-30392 in one
    payment), by customer name + exact amount with no reference (Larkhollow
    SI-30361), and by a reference written without its hyphen (Grayling & Fosse
    "SI30404", matched on name + amount)
  - 7 customers have overdue invoices to chase, at three tiers: Reminder
    (Lessmoor, Larkhollow, Grayling & Fosse), Second reminder (Riverholt, Corvel,
    Quarrendon Court) and Final notice (Ambleford)

Deliberate problems planted for the agent to find (11 exceptions):
  1  Ambleford Property Management   SI-30318 is 83 days overdue: final notice drafted, needs approval (High)
  2  Lessmoor Academy Trust          SI-30388 marked "Disputed - snagging list outstanding": left out of the chase
  3  BANK GIRO CREDIT 000418         £1,950.00 paid in with no customer name or invoice number: not allocated
  4  Riverholt Housing Association   SI-30372 part paid (£12,000.00 of £16,350.00): balance goes in the chase
  5  Corvel Logistics Ltd            owes £12,480.00 against a £10,000 credit limit
  6  Quarrendon Court RMC Ltd        overdue invoices but no accounts email on the customer list
  7  Oakmere Medical Centre          credit note CN-0412 leaves the account £540.00 in credit
  8  Riverholt new invoicing address email covers two projects (Marsh View and voids): can't pick a folder
  9  Brightline Trade Paints delivery note quotes job J-4211, which is not on the register (J-4121?)
 10  Pelham Rise Management Ltd      new enquiry for a site with no project yet: nothing to file it under
 11  Quarrendon Court photo          signed completion sheet sent as a JPG photo: cannot be read without OCR

Filing: 20 of the 23 readable documents go to a project folder. 15 quote the
job number; 5 only name the site (Kestrelgate remittance, Saltings remittance,
Larkhollow room access email, Corvel statement request, Quarrendon Court
letter) and are filed on the site keyword from the project register.
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

COMPANY = "Demo Decorating Contractors Ltd"
BRANCH = "Erith branch"
COMPANY_ADDRESS = ["Unit 4, Example Trade Park", "Erith DA8 2XX"]
COMPANY_EMAIL = "erith.office@demo-decorating.example"
COMPANY_PHONE = "020 7946 0410"

# ---------------------------------------------------------------- reference data

PROJECTS = [  # ref, name, client, site, keywords
    ("J-4102", "External redecoration programme 2026 - Marsh View Estate", "Riverholt Housing Association",
     "Marsh View Estate, Abbey Wood", "Heron Court; Plover Court"),
    ("J-4115", "Summer works 2026 - classrooms and corridors", "Lessmoor Academy Trust",
     "Lessmoor Primary School, Slade Green", ""),
    ("J-4121", "Communal areas redecoration - Kingsridge House", "Ambleford Property Management Ltd",
     "Kingsridge House, Dartford", ""),
    ("J-4126", "New-build painting package - Wharfside Quarter", "Kestrelgate Construction Ltd",
     "Wharfside Quarter, Greenhithe", ""),
    ("J-4130", "Residents' rooms redecoration - Saltings Lodge", "Saltings Care Group Ltd",
     "Saltings Lodge, Sidcup", ""),
    ("J-4134", "Bedroom refurbishment, floors 2 and 3", "Larkhollow Hotels Ltd",
     "Larkhollow Hotel, Bexleyheath", ""),
    ("J-4138", "Warehouse steelwork repaint and line marking", "Corvel Logistics Ltd",
     "Example Distribution Park, Belvedere", ""),
    ("J-4141", "External decoration and fire door upgrade", "Quarrendon Court RMC Ltd",
     "Quarrendon Court, Welling", ""),
    ("J-4144", "Waiting room and consulting rooms redecoration", "Oakmere Medical Centre",
     "Oakmere Medical Centre, Crayford", ""),
    ("J-4147", "Void property repairs and redecoration (call-off)", "Riverholt Housing Association",
     "Riverholt void properties (various)", "voids programme; void property"),
    ("J-4150", "Void flat redecorations (rolling)", "Grayling & Fosse Lettings Ltd",
     "Let flats (various)", ""),
]

CUSTOMERS = [  # name, ref, contact, email, terms, credit limit
    ("Riverholt Housing Association", "RIVERH01", "Natalie Okafor", "accounts.payable@riverholt-ha.example", 30, 60000),
    ("Lessmoor Academy Trust", "LESSMO01", "Rebecca Thorne", "finance@lessmoor-trust.example", 30, 25000),
    ("Ambleford Property Management Ltd", "AMBLEF01", "Daniel Cho", "accounts@ambleford-pm.example", 30, 15000),
    ("Kestrelgate Construction Ltd", "KESTRE01", "Paula Mensah", "payables@kestrelgate.example", 45, 40000),
    ("Saltings Care Group Ltd", "SALTIN01", "Mark Fenton", "purchase.ledger@saltings-care.example", 30, 20000),
    ("Larkhollow Hotels Ltd", "LARKHO01", "Sophie Kendrick", "accounts@larkhollow-hotels.example", 30, 15000),
    ("Corvel Logistics Ltd", "CORVEL01", "Aisha Rahman", "ap@corvel-logistics.example", 30, 10000),
    ("Quarrendon Court RMC Ltd", "QUARRE01", "Brian Ellwood", "", 14, 5000),  # planted: no email
    ("Oakmere Medical Centre", "OAKMER01", "Linda Hayes", "manager@oakmere-medical.example", 30, 5000),
    ("Grayling & Fosse Lettings Ltd", "GRAYLI01", "Chloe Banner", "maintenance@grayling-fosse.example", 14, 5000),
]

LEDGER = [  # customer, invoice, invoice date, due date, project, amount, paid, notes
    ("Riverholt Housing Association", "SI-30341", "03/08/2026", "02/09/2026", "J-4102", 14820.00, 0, "Valuation 3"),
    ("Riverholt Housing Association", "SI-30372", "01/09/2026", "01/10/2026", "J-4102", 16350.00, 0, "Valuation 4"),
    ("Riverholt Housing Association", "SI-30395", "24/09/2026", "24/10/2026", "J-4147", 2874.00, 0, "Voids: 3 properties"),
    ("Riverholt Housing Association", "SI-30401", "01/10/2026", "31/10/2026", "J-4102", 15960.00, 0, "Valuation 5"),
    ("Riverholt Housing Association", "SI-30419", "15/10/2026", "14/11/2026", "J-4147", 1236.00, 0, "Voids: 1 property"),
    ("Lessmoor Academy Trust", "SI-30388", "18/09/2026", "18/10/2026", "J-4115", 9744.00, 0,
     "Disputed - snagging list outstanding (email 28/09)"),
    ("Lessmoor Academy Trust", "SI-30389", "18/09/2026", "18/10/2026", "J-4115", 1512.00, 0, "Variation: hall ceiling"),
    ("Ambleford Property Management Ltd", "SI-30318", "15/07/2026", "14/08/2026", "J-4121", 6480.00, 0, "Stage 1"),
    ("Ambleford Property Management Ltd", "SI-30349", "12/08/2026", "11/09/2026", "J-4121", 5940.00, 0, "Stage 2"),
    ("Kestrelgate Construction Ltd", "SI-30364", "31/08/2026", "15/10/2026", "J-4126", 11400.00, 0, "Application 3"),
    ("Kestrelgate Construction Ltd", "SI-30398", "30/09/2026", "14/11/2026", "J-4126", 9120.00, 0, "Application 4"),
    ("Saltings Care Group Ltd", "SI-30377", "10/09/2026", "10/10/2026", "J-4130", 4680.00, 0, "Rooms 1-12"),
    ("Saltings Care Group Ltd", "SI-30392", "22/09/2026", "22/10/2026", "J-4130", 3150.00, 0, "Rooms 13-20"),
    ("Saltings Care Group Ltd", "SI-30410", "08/10/2026", "07/11/2026", "J-4130", 5220.00, 0, "Lounge and corridors"),
    ("Larkhollow Hotels Ltd", "SI-30361", "28/08/2026", "27/09/2026", "J-4134", 3240.00, 0, "Deposit 25%"),
    ("Larkhollow Hotels Ltd", "SI-30384", "15/09/2026", "15/10/2026", "J-4134", 7560.00, 0, "Floor 2"),
    ("Larkhollow Hotels Ltd", "SI-30407", "06/10/2026", "05/11/2026", "J-4134", 6890.00, 0, "Floor 3"),
    ("Corvel Logistics Ltd", "SI-30352", "12/08/2026", "11/09/2026", "J-4138", 4320.00, 0, "Steelwork bays 1-4"),
    ("Corvel Logistics Ltd", "SI-30380", "11/09/2026", "11/10/2026", "J-4138", 3960.00, 0, "Steelwork bays 5-8"),
    ("Corvel Logistics Ltd", "SI-30413", "09/10/2026", "08/11/2026", "J-4138", 4200.00, 0, "Line marking"),
    ("Quarrendon Court RMC Ltd", "SI-30370", "04/09/2026", "18/09/2026", "J-4141", 2460.00, 0, "External decoration"),
    ("Quarrendon Court RMC Ltd", "SI-30396", "25/09/2026", "09/10/2026", "J-4141", 1380.00, 0, "Fire doors: flats 1-6"),
    ("Oakmere Medical Centre", "CN-0412", "20/10/2026", "", "J-4144", -540.00, 0,
     "Credit note: consulting room 3 charged twice on SI-30359 (paid)"),
    ("Grayling & Fosse Lettings Ltd", "SI-30393", "22/09/2026", "06/10/2026", "J-4150", 960.00, 0, "Flat 2, 41 Example Street"),
    ("Grayling & Fosse Lettings Ltd", "SI-30404", "02/10/2026", "16/10/2026", "J-4150", 1140.00, 0, "Flat 5, 8 Example Mews"),
    ("Grayling & Fosse Lettings Ltd", "SI-30416", "13/10/2026", "27/10/2026", "J-4150", 720.00, 0, "Flat 1, 17 Example Place"),
]

BANK = [  # date, description, money out, money in
    ("01/10/2026", "DD HMRC VAT", 18240.00, None),
    ("02/10/2026", "BACS BRIGHTLINE TRADE PAINTS", 6410.52, None),
    ("06/10/2026", "BACS FASTRISE ACCESS HIRE", 2184.00, None),
    ("08/10/2026", "RIVERHOLT HOUSING ASSOC SI-30341", None, 14820.00),
    ("09/10/2026", "DD FLEETCARD FUEL", 1126.38, None),
    ("14/10/2026", "KESTRELGATE CONSTRUCTION SI-30364", None, 11400.00),
    ("15/10/2026", "BACS WAGES WEEKLY", 21480.00, None),
    ("16/10/2026", "FP LARKHOLLOW HOTELS LTD", None, 3240.00),
    ("19/10/2026", "BACS SKIPWELL WASTE SERVICES", 384.00, None),
    ("21/10/2026", "SALTINGS CARE GROUP REMIT 7781 SI-30377 SI-30392", None, 7830.00),
    ("22/10/2026", "RIVERHOLT HOUSING ASSOC SI-30372", None, 12000.00),  # planted: part payment
    ("22/10/2026", "DD HMRC PAYE NIC", 9875.40, None),
    ("26/10/2026", "BACS BRIGHTLINE TRADE PAINTS", 4892.16, None),
    ("28/10/2026", "FP GRAYLING FOSSE SI30404", None, 1140.00),  # reference without hyphen: matched on name + amount
    ("29/10/2026", "BACS WAGES WEEKLY", 21365.00, None),
    ("30/10/2026", "BANK GIRO CREDIT 000418", None, 1950.00),  # planted: no customer or invoice shown
    ("02/11/2026", "DD VANLINE LEASING", 1980.00, None),
    ("03/11/2026", "BACS FASTRISE ACCESS HIRE", 1092.00, None),
    ("04/11/2026", "CARD FEES OCT", 46.85, None),
]
OPENING_BALANCE = 48215.62

# ------------------------------------------------------------------------ PDFs


def _pdf(blocks: list[tuple[str, str]], *, size=(595, 842), margin=56) -> bytes:
    """Tiny layout engine: (style, text) blocks top to bottom; long text wraps.

    Styles: big, title, h, b, n, s, i, gap, rule; '|' in a 'row' splits columns."""
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, invariant=1)  # reproducible bytes
    width, height = size
    y = height - margin
    fonts = {"title": ("Helvetica-Bold", 16), "h": ("Helvetica-Bold", 11), "b": ("Helvetica-Bold", 9.5),
             "n": ("Helvetica", 9.5), "s": ("Helvetica", 8), "i": ("Helvetica-Oblique", 9.5), "big": ("Helvetica-Bold", 13),
             "row": ("Helvetica", 9.5), "rowb": ("Helvetica-Bold", 9.5)}
    for style, text in blocks:
        if y < margin + 20:
            c.showPage()
            y = height - margin
        if style == "gap":
            y -= 8
            continue
        if style == "rule":
            c.setStrokeColorRGB(0.75, 0.78, 0.82)
            c.line(margin, y + 4, width - margin, y + 4)
            y -= 6
            continue
        font, sz = fonts[style]
        c.setFont(font, sz)
        if style in ("row", "rowb"):
            cols = text.split("|")
            usable = width - 2 * margin
            xs = [margin + usable * i / len(cols) for i in range(len(cols))]
            if len(cols) == 3:
                xs = [margin, margin + usable * 0.62, margin + usable * 0.8]
            for i, (x, col) in enumerate(zip(xs, cols)):
                if i == 0:
                    c.drawString(x, y, col)
                else:
                    right = xs[i + 1] - 6 if i + 1 < len(xs) else width - margin
                    c.drawRightString(right, y, col)
            y -= sz + 5
            continue
        for line in simpleSplit(text, font, sz, width - 2 * margin) or [""]:
            c.drawString(margin, y, line)
            y -= sz + 4
        y -= 2
    c.showPage()
    c.save()
    return buf.getvalue()


def letterhead(name: str, address: list[str], contact: str) -> list[tuple[str, str]]:
    return [("big", name)] + [("n", a) for a in address] + [("s", contact), ("rule", "")]


def to_us(attn: str = "") -> list[tuple[str, str]]:
    who = [("n", attn)] if attn else []
    return who + [("n", f"{COMPANY} ({BRANCH})")] + [("n", a) for a in COMPANY_ADDRESS] + [("gap", "")]


def money(v: float) -> str:
    return f"£{v:,.2f}"

# --------------------------------------------------------------------- emails


def eml(*, sender: str, subject: str, date: str, body: str, to: str = COMPANY_EMAIL, cc: str = "") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = format_datetime(pd.Timestamp(date).tz_localize("Europe/London").to_pydatetime())
    msg["Message-ID"] = f"<{hashlib.sha1((subject + date).encode()).hexdigest()[:16]}@mail.example>"
    msg.set_content(body)
    return bytes(msg)

# ------------------------------------------------------------------ documents


def documents() -> dict[str, bytes]:
    d: dict[str, bytes] = {}

    # Riverholt Housing Association: planned programme J-4102 and voids J-4147 --------------------------
    rh_head = letterhead("Riverholt Housing Association", ["Riverside House, 2 Example Wharf", "Woolwich SE18 0XX"],
                         "Asset Management · Tel 020 7946 0127 · assets@riverholt-ha.example")
    d["2026-08-03_riverholt_letter-of-acceptance_J-4102.pdf"] = _pdf(rh_head + to_us("For the attention of Paul Denning, Branch Manager") + [
        ("n", "3 August 2026"), ("gap", ""),
        ("title", "Letter of acceptance"),
        ("b", "Contract: External redecoration programme 2026 - Marsh View Estate (your job J-4102)"),
        ("n", "Our contract reference: RHA/AM/2026/014"), ("gap", ""),
        ("n", "Following the tender returned on 14 July 2026, Riverholt Housing Association accepts your tender for the "
              "external redecoration of Heron Court, Plover Court and Avocet Court, Marsh View Estate, in the sum of "
              "£148,600.00 excluding VAT."),
        ("n", "The works will be carried out under the terms of the measured term contract dated 1 April 2025. Start on "
              "site: 17 August 2026. Completion: 18 December 2026. Retention: 3%, half released at completion."),
        ("n", "Monthly valuations are to be submitted to the contract administrator, Graham Lister, by the last working day "
              "of each month. Payment is due 30 days from the date of a valid invoice."),
        ("gap", ""), ("n", "Please sign and return the attached copy to confirm acceptance."), ("gap", ""),
        ("n", "Yours faithfully,"), ("n", "Andrea Wills"), ("n", "Head of Asset Management, Riverholt Housing Association"),
    ])
    d["2026-10-06_riverholt_variation-VI-07_J-4102.eml"] = eml(
        sender="Graham Lister <g.lister@riverholt-ha.example>", subject="J-4102 Marsh View - Variation instruction VI-07",
        date="2026-10-06 10:42",
        body="Hi Kerry,\n\nFurther to our site walk on Friday, please treat this email as variation instruction VI-07 on "
             "contract RHA/AM/2026/014 (your job J-4102):\n\n- Replace and paint 14 rotten fascia boards at Plover Court "
             "(rear elevation)\n- Additional coat of masonry paint to the bin store walls at Heron Court\n\nPlease send me "
             "your price for both items by 16 October. Do not start the fascia work until the price is agreed.\n\n"
             "Regards,\nGraham Lister\nContract Administrator, Riverholt Housing Association")
    d["2026-10-14_marsh-view_site-meeting-minutes-06.pdf"] = _pdf(rh_head + [
        ("title", "Site progress meeting no. 6"),
        ("n", "Contract: Marsh View Estate external redecoration (contractor's job no. J-4102)"),
        ("n", "Date: 14 October 2026, site cabin, Heron Court"),
        ("n", "Present: Graham Lister (Riverholt, CA), Kerry Walsh (contracts manager), Dean Foley (site supervisor), "
              "Mrs P. Grant (residents' representative)"), ("gap", ""),
        ("h", "1. Progress"),
        ("n", "Heron Court complete apart from bin stores (VI-07). Plover Court 60% complete. Avocet Court scaffold "
              "to go up week commencing 26 October."),
        ("h", "2. Health and safety"), ("n", "No accidents reported. Scaffold inspection tags in date."),
        ("h", "3. Residents"),
        ("n", "Two complaints about paint on balcony glass at Heron Court, flats 12 and 14. Contractor to clean by 21 October."),
        ("h", "4. Valuation"),
        ("n", "Valuation 5 agreed at £13,300.00 plus VAT. Contractor to invoice. CA confirmed valuation 4 is with "
              "Riverholt finance for payment."),
        ("h", "5. Next meeting"), ("n", "11 November 2026, 10:00, Heron Court site cabin."),
    ])
    d["2026-10-19_riverholt_works-order-WO-55817_J-4147.pdf"] = _pdf(rh_head + to_us() + [
        ("title", "Works order WO-55817"),
        ("n", "Date issued: 19 October 2026 · Priority: void (10 working days)"),
        ("n", "Contractor job reference: J-4147 (void property call-off)"), ("gap", ""),
        ("b", "Property: 7 Example Gardens, Plumstead SE18 0XX (void)"),
        ("rowb", "Item|Qty|Value"), ("rule", ""),
        ("row", "Mist coat and two coats emulsion, all rooms|1|£1,180.00"),
        ("row", "Gloss all internal joinery|1|£420.00"),
        ("row", "Remove graffiti and stain-block hallway|1|£165.00"), ("rule", ""),
        ("rowb", "Order value (excluding VAT)||£1,765.00"), ("gap", ""),
        ("n", "Please quote WO-55817 and your job number on your invoice. Keys from the Woolwich office."),
        ("n", "Issued by: Voids Team, Riverholt Housing Association"),
    ])
    d["2026-10-27_riverholt_new-invoicing-address.eml"] = eml(
        sender="Natalie Okafor <accounts.payable@riverholt-ha.example>",
        subject="Change of invoicing address - all Riverholt contracts", date="2026-10-27 15:05",
        body="Dear supplier,\n\nFrom 1 November 2026 Riverholt Housing Association is moving to a single purchase "
             "ledger team. Please send all invoices for both your contracts with us - the Marsh View Estate "
             "redecoration and the void property programme - to invoices@riverholt-ha.example instead of this "
             "address.\n\nInvoices must quote our order or works order number, or they will be returned. Payment "
             "terms are unchanged.\n\nKind regards,\nNatalie Okafor\nAccounts Payable, Riverholt Housing Association")

    # Lessmoor Academy Trust: J-4115 ----------------------------------------------------------------------
    d["2026-08-28_lessmoor_handover-certificate_J-4115.pdf"] = _pdf(
        letterhead(COMPANY, COMPANY_ADDRESS, f"{BRANCH} · Tel {COMPANY_PHONE} · {COMPANY_EMAIL}") + [
            ("title", "Handover certificate"),
            ("n", "Job: J-4115 Summer works 2026 - classrooms and corridors"),
            ("n", "Client: Lessmoor Academy Trust · Site: Lessmoor Primary School, Slade Green"), ("gap", ""),
            ("n", "The works listed in the schedule dated 14 July 2026 were handed over on 28 August 2026, before the "
                  "start of the autumn term, subject to the attached snagging list (14 items)."),
            ("n", "Snagging to be completed within 21 days of handover, outside school hours."), ("gap", ""),
            ("n", "For the contractor: Dean Foley, Site Supervisor · 28/08/2026"),
            ("n", "For the client: R. Thorne, Business Manager · 28/08/2026"),
        ])
    d["2026-09-28_lessmoor_snagging-query.eml"] = eml(
        sender="Rebecca Thorne <finance@lessmoor-trust.example>",
        subject="RE: Invoice SI-30388 - J-4115 Lessmoor Primary summer works", date="2026-09-28 16:20",
        body="Hello,\n\nWe have received invoice SI-30388 for £9,744.00 (final account, summer works). We won't be "
             "able to pay it until the snagging list from the handover on 28 August is finished. 9 of the 14 items are "
             "still outstanding, including the paint runs in corridor B and the damaged skirting in classroom 4.\n\n"
             "Invoice SI-30389 for the hall ceiling is fine and will go in our next payment run.\n\nPlease let me know "
             "when your team can come back - it will need to be after 3.30pm or at the weekend.\n\nThanks,\n"
             "Rebecca Thorne\nBusiness Manager, Lessmoor Academy Trust")

    # Ambleford Property Management: J-4121 ---------------------------------------------------------------
    d["2026-10-12_ambleford_payment-update_J-4121.eml"] = eml(
        sender="Daniel Cho <d.cho@ambleford-pm.example>", subject="Kingsridge House (J-4121) - your invoices",
        date="2026-10-12 11:58",
        body="Hi,\n\nSorry for the delay on your invoices for the communal redecoration at Kingsridge House. The works "
             "are paid for from the building's service charge and we are still collecting this year's contributions "
             "from the leaseholders.\n\nI hope to release payment by the end of November, but I can't promise a date "
             "yet. I'll keep you posted.\n\nBest wishes,\nDaniel Cho\nProperty Manager, Ambleford Property Management Ltd")
    d["2026-10-21_brightline_delivery-note-DN-60417.pdf"] = _pdf(
        letterhead("Brightline Trade Paints Ltd", ["Depot 2, Example Industrial Estate", "Thurrock RM20 0XX"],
                   "Trade counter 01632 960 744 · orders@brightline-paints.example") + [
            ("title", "Delivery note DN-60417"),
            ("n", "Delivered: 21 October 2026 · Account: DEMO-ERITH"),
            ("n", "Customer order ref: J-4211 · Ordered by: K. Walsh"), ("gap", ""),
            ("rowb", "Product|Qty|Unit"), ("rule", ""),
            ("row", "Acrylic eggshell, white, 10L|6|tins"),
            ("row", "Vinyl matt emulsion, magnolia, 10L|8|tins"),
            ("row", "Water-based satinwood, brilliant white, 5L|4|tins"),
            ("row", "Dust sheets, cotton twill 12x9ft|10|each"), ("rule", ""), ("gap", ""),
            ("n", "Received in good condition. Signed: D. Foley"),
            ("s", "Goods remain our property until paid for in full. Invoice to follow."),
        ])

    # Kestrelgate Construction: J-4126 --------------------------------------------------------------------
    kg_head = letterhead("Kestrelgate Construction Ltd", ["Kestrel House, 9 Example Parade", "Gravesend DA11 0XX"],
                         "Commercial Department · Tel 01632 960 381 · commercial@kestrelgate.example")
    d["2026-08-17_kestrelgate_subcontract-order-KC-SO-0388_J-4126.pdf"] = _pdf(kg_head + to_us() + [
        ("title", "Subcontract order KC-SO-0388"),
        ("n", "Date: 17 August 2026 · Your job ref: J-4126"),
        ("n", "Project: Wharfside Quarter, Block B (46 apartments)"), ("gap", ""),
        ("n", "Scope: mist coat and two finish coats to all walls and ceilings, eggshell to kitchens and bathrooms, "
              "satinwood to internal joinery, to the specification and drawings issued with the enquiry."),
        ("n", "Subcontract sum: £86,400.00. Monthly applications by the 25th; payment notice within 5 days of the due "
              "date; final date for payment 45 days after the invoice date. Retention: none on this package."),
        ("n", "Programme: start 1 September 2026, complete 27 November 2026."), ("gap", ""),
        ("n", "Signed for Kestrelgate Construction Ltd: Ian Royle, Senior Quantity Surveyor"),
    ])
    d["2026-09-24_kestrelgate_programme-update_J-4126.eml"] = eml(
        sender="Ian Royle <i.royle@kestrelgate.example>", subject="J-4126 Wharfside Quarter - revised programme rev C",
        date="2026-09-24 08:31",
        body="Morning Kerry,\n\nAttached is programme revision C for Block B. The dryliners are running about a week "
             "late, so your start on floors 4 to 6 moves from 12 October to 19 October. Overall handover of Block B "
             "is unchanged at 27 November.\n\nCan you confirm you can put an extra two decorators on from 19 October "
             "to hold the finish date?\n\nThanks,\nIan Royle\nSenior QS, Kestrelgate Construction Ltd")
    d["2026-10-14_kestrelgate_remittance-advice.eml"] = eml(
        sender="Kestrelgate Payables <payables@kestrelgate.example>", subject="Remittance advice - payment run 14/10/2026",
        date="2026-10-14 07:15",
        body="Remittance advice\n\nPayer: Kestrelgate Construction Ltd\nPayee: Demo Decorating Contractors Ltd\n"
             "Payment date: 14/10/2026 by BACS\n\nYour invoice   Description                               Amount\n"
             "SI-30364       Application 3 - Wharfside Quarter painting   £11,400.00\n\nTotal paid: £11,400.00\n\n"
             "This is an automated message from Kestrelgate Construction Ltd.")

    # Saltings Care Group: J-4130 -------------------------------------------------------------------------
    d["2026-09-02_saltings_rams-approval_J-4130.eml"] = eml(
        sender="Joy Adeyemi <manager.saltingslodge@saltings-care.example>",
        subject="J-4130 - RAMS approved for residents' rooms", date="2026-09-02 13:44",
        body="Dear Kerry,\n\nThank you for the risk assessment and method statement for the redecoration of residents' "
             "rooms (your job J-4130). It is approved, with two conditions:\n\n1. Low-odour, water-based paints only in "
             "occupied areas.\n2. No more than two rooms out of use at any time, and all work between 9.30am and "
             "4pm.\n\nPlease report to reception on arrival each day.\n\nKind regards,\nJoy Adeyemi\nHome Manager, "
             "Saltings Lodge")
    d["2026-10-21_saltings_remittance-7781.eml"] = eml(
        sender="Saltings Care Group Finance <purchase.ledger@saltings-care.example>",
        subject="Remittance 7781 - Demo Decorating Contractors Ltd", date="2026-10-21 09:02",
        body="Please find below details of our payment to you today.\n\nRemittance no. 7781 · BACS · 21/10/2026\n\n"
             "SI-30377  Saltings Lodge redecoration, rooms 1-12    £4,680.00\n"
             "SI-30392  Saltings Lodge redecoration, rooms 13-20   £3,150.00\n\nTotal  £7,830.00\n\n"
             "Mark Fenton\nFinance Officer, Saltings Care Group Ltd")

    # Larkhollow Hotels: J-4134 ---------------------------------------------------------------------------
    d["2026-09-07_larkhollow_signed-quotation-Q-2207_J-4134.pdf"] = _pdf(
        letterhead(COMPANY, COMPANY_ADDRESS, f"{BRANCH} · Tel {COMPANY_PHONE} · {COMPANY_EMAIL}") + [
            ("title", "Quotation Q-2207 - acceptance"),
            ("n", "Client: Larkhollow Hotels Ltd · Site: Larkhollow Hotel, Bexleyheath · Job: J-4134"), ("gap", ""),
            ("rowb", "Item|Rooms|Price"), ("rule", ""),
            ("row", "Bedroom redecoration, floor 2|18|£6,300.00"),
            ("row", "Bedroom redecoration, floor 3|16|£5,741.67"),
            ("row", "Corridors, floors 2 and 3|2|£960.00"), ("rule", ""),
            ("rowb", "Total excluding VAT||£13,001.67"), ("gap", ""),
            ("n", "Terms: deposit of £2,700.00 plus VAT on acceptance; each floor invoiced on completion; corridors and "
                  "the deposit settled in the final account. Payment within 30 days of invoice."),
            ("n", "Accepted for Larkhollow Hotels Ltd: Tom Whitlock, General Manager · 07/09/2026"),
        ])
    d["2026-10-15_larkhollow_room-access.eml"] = eml(
        sender="Tom Whitlock <gm@larkhollow-hotels.example>", subject="Room access next week - floor 3",
        date="2026-10-15 17:26",
        body="Hi Dean,\n\nWe have a wedding party in on Saturday 24 October, so floor 3 at the Larkhollow Hotel is fully "
             "booked from Friday 23 to Sunday 25 October. Please plan to finish rooms 301 to 308 by Thursday 22nd and "
             "start the rest on Monday 26th.\n\nHousekeeping will leave the keys at reception as usual.\n\nThanks,\n"
             "Tom Whitlock\nGeneral Manager")

    # Corvel Logistics: J-4138 ----------------------------------------------------------------------------
    cv_head = letterhead("Corvel Logistics Ltd", ["Unit 9, Example Distribution Park", "Belvedere DA17 0XX"],
                         "Tel 01632 960 552 · ap@corvel-logistics.example")
    d["2026-09-01_corvel_purchase-order-CV-PO-11873_J-4138.pdf"] = _pdf(cv_head + to_us() + [
        ("title", "Purchase order CV-PO-11873"),
        ("n", "Order date: 1 September 2026 · Supplier quote ref: J-4138 / Q-2189"), ("gap", ""),
        ("rowb", "Description|Qty|Net"), ("rule", ""),
        ("row", "Prepare and repaint racking steelwork, bays 1-4|1|£3,600.00"),
        ("row", "Prepare and repaint racking steelwork, bays 5-8|1|£3,300.00"),
        ("row", "Re-line warehouse floor walkways and loading bays|1|£3,500.00"), ("rule", ""),
        ("rowb", "Order total (excluding VAT)||£10,400.00"), ("gap", ""),
        ("n", "Invoices must quote CV-PO-11873. Payment terms: 30 days from invoice."),
        ("n", "Authorised: A. Rahman, Accounts Payable"),
    ])
    d["2026-10-23_corvel_statement-request.eml"] = eml(
        sender="Aisha Rahman <ap@corvel-logistics.example>", subject="Statement of account please",
        date="2026-10-23 10:11",
        body="Hello,\n\nCould you send us a statement of account for Corvel Logistics, Unit 9, Example Distribution "
             "Park? We are reconciling our ledger for month end and want to make sure we have all your invoices.\n\n"
             "Also, would you consider 60-day terms for future work? Our other contractors are on 60 days.\n\n"
             "Many thanks,\nAisha Rahman\nAccounts Payable, Corvel Logistics Ltd")

    # Quarrendon Court RMC: J-4141 ------------------------------------------------------------------------
    d["2026-09-11_quarrendon_fire-doors-letter.pdf"] = _pdf(
        letterhead("Quarrendon Court RMC Ltd", ["c/o Flat 12, Quarrendon Court", "Welling DA16 0XX"],
                   "Residents' management company · Directors: B. Ellwood (chair), S. Moyo") + to_us() + [
            ("n", "11 September 2026"), ("gap", ""),
            ("b", "External decoration and fire door upgrade, Quarrendon Court"),
            ("n", "Dear Sirs,"),
            ("n", "Thank you for completing the external decoration last week. The directors are pleased with the work."),
            ("n", "We would like to go ahead with the fire door upgrades for flats 1 to 6 as quoted, at £1,150.00 plus "
                  "VAT. Please contact me on 07700 900 318 to arrange access with the residents."),
            ("n", "As we are a small volunteer-run company, please send invoices and statements by post to the address "
                  "above. We do not have an office email address."),
            ("gap", ""), ("n", "Yours faithfully,"), ("n", "Brian Ellwood, Chair"),
        ])
    # planted: a photo of a signed sheet - the agent cannot read it without OCR
    d["2026-10-29_quarrendon_signed-completion-photo.jpg"] = _photo()

    # Oakmere Medical Centre: J-4144 ----------------------------------------------------------------------
    d["2026-08-24_oakmere_minor-works-agreement_J-4144.pdf"] = _pdf(
        letterhead(COMPANY, COMPANY_ADDRESS, f"{BRANCH} · Tel {COMPANY_PHONE} · {COMPANY_EMAIL}") + [
            ("title", "Minor works agreement"),
            ("n", "Job: J-4144 · Date: 24 August 2026"),
            ("n", "Employer: Oakmere Medical Centre, Crayford · Contractor: Demo Decorating Contractors Ltd"), ("gap", ""),
            ("n", "Works: redecoration of the waiting room, reception and consulting rooms 1 to 5, out of surgery "
                  "hours (after 6.30pm and Saturdays)."),
            ("n", "Contract sum: £7,450.00 excluding VAT. Payment within 30 days of invoice. Defects period: 6 months."),
            ("gap", ""), ("n", "Signed for the employer: Linda Hayes, Practice Manager"),
            ("n", "Signed for the contractor: Paul Denning, Branch Manager"),
        ])
    d["2026-10-20_oakmere_duplicate-charge.eml"] = eml(
        sender="Linda Hayes <manager@oakmere-medical.example>", subject="Invoice SI-30359 - consulting room 3 (J-4144)",
        date="2026-10-20 12:37",
        body="Hello,\n\nWe paid invoice SI-30359 in full last month, but I've now noticed that consulting room 3 is "
             "charged twice on it (lines 4 and 6, £450.00 plus VAT each).\n\nThanks for confirming on the phone that "
             "you'll issue a credit note. Please let me know whether you will refund it or take it off your next "
             "invoice - we don't have any more work booked with you at the moment.\n\nKind regards,\nLinda Hayes\n"
             "Practice Manager, Oakmere Medical Centre")

    # Grayling & Fosse Lettings: J-4150 -------------------------------------------------------------------
    d["2026-10-02_grayling-fosse_works-instruction_J-4150.eml"] = eml(
        sender="Chloe Banner <maintenance@grayling-fosse.example>",
        subject="Works instruction GF-2290 - Flat 5, 8 Example Mews (your ref J-4150)", date="2026-10-02 09:20",
        body="Hi,\n\nPlease go ahead with the void redecoration at Flat 5, 8 Example Mews, as per your price of "
             "£950.00 plus VAT under the rolling agreement (your ref J-4150).\n\nThe new tenant moves in on 16 "
             "October, so the work must be finished by the 14th. Keys are at our Bromley office.\n\nWorks instruction "
             "number GF-2290 - please quote it on the invoice.\n\nThanks,\nChloe Banner\nMaintenance Coordinator, "
             "Grayling & Fosse Lettings Ltd")

    # A new enquiry: no project yet -------------------------------------------------------------------------
    d["2026-10-26_pelham-rise_quote-request.eml"] = eml(
        sender="Helen Brady <h.brady@pelhamrise-mgmt.example>", subject="Quote request - stairwell redecoration",
        date="2026-10-26 14:03",
        body="Good afternoon,\n\nWe manage Pelham Rise, a block of 24 flats in Erith. We are looking for a contractor to "
             "redecorate the two communal stairwells and entrance lobby early in the new year.\n\nCould someone visit "
             "to measure up and quote? Weekday mornings are best. A copy of the fire risk assessment is available if "
             "you need it.\n\nKind regards,\nHelen Brady\nBlock Manager, Pelham Rise Management Ltd")
    return d


def _photo() -> bytes:
    """A small JPEG of a 'photographed' sheet: no text layer, so it needs OCR."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (480, 640), (238, 236, 230))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 440, 600], fill=(252, 252, 250), outline=(190, 190, 190))
    for y in range(90, 560, 28):
        draw.line([70, y, 70 + (y * 37) % 300 + 60, y], fill=(120, 120, 130), width=3)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()

# ---------------------------------------------------------------- spreadsheets


def ledger_frame() -> pd.DataFrame:
    return pd.DataFrame([{"Customer": c, "Invoice No": i, "Invoice Date": d, "Due Date": due, "Project": p,
                          "Amount": a, "Paid": paid, "Notes": n} for c, i, d, due, p, a, paid, n in LEDGER])


def bank_frame() -> pd.DataFrame:
    rows, balance = [], OPENING_BALANCE
    for date, desc, out, inn in BANK:
        balance = round(balance - (out or 0) + (inn or 0), 2)
        rows.append({"Date": date, "Description": desc, "Money out": f"{out:.2f}" if out else "",
                     "Money in": f"{inn:.2f}" if inn else "", "Balance": f"{balance:.2f}"})
    return pd.DataFrame(rows)


def customers_frame() -> pd.DataFrame:
    return pd.DataFrame([{"Customer": n, "Account Ref": r, "Contact": c, "Email": e, "Terms (days)": t, "Credit Limit": l}
                         for n, r, c, e, t, l in CUSTOMERS])


def projects_frame() -> pd.DataFrame:
    return pd.DataFrame([{"Project Ref": r, "Project Name": n, "Client": c, "Site": s, "Keywords": k}
                         for r, n, c, s, k in PROJECTS])

# --------------------------------------------------------------------- main


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()
    docs = documents()
    for name, data in docs.items():
        (INBOX / name).write_bytes(data)
    with pd.ExcelWriter(OUT / "sales_ledger_open_invoices.xlsx", engine="xlsxwriter") as writer:
        ledger_frame().to_excel(writer, index=False, sheet_name="Open invoices")
        writer.sheets["Open invoices"].set_column(0, 0, 34)
        writer.sheets["Open invoices"].set_column(7, 7, 52)
        writer.book.set_properties({"created": datetime(2026, 11, 5, 8, 30)})  # reproducible bytes
    bank_frame().to_csv(OUT / "bank_statement_oct-2026.csv", index=False)
    customers_frame().to_csv(OUT / "customer_list.csv", index=False)
    projects_frame().to_csv(OUT / "project_register.csv", index=False)
    print(f"Wrote {len(docs)} documents to {INBOX} and 4 spreadsheets to {OUT}")


if __name__ == "__main__":
    sys.exit(main())

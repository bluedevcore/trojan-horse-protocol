"""Generate the synthetic sample data for the QuickBooks Bookkeeping Agent demo.

Everything here is invented: the company ("Demo Company Ltd"), suppliers,
customers, staff, amounts, VAT numbers and bank details. Bank sort codes start
00- (not issued to any bank), phone numbers are Ofcom drama numbers, email
domains end .example. No real personal or company data. Re-run to regenerate:

    python clients/cosgrove-cosgrove/sample_data/generate.py

October 2026 month end. Inbox: 28 documents (14 supplier invoices / credit
notes as PDF or email, one of them a duplicate, and 14 receipts and paid
invoices for card spend), a
company credit card statement (17 card payments + 1 repayment), a payroll
bureau report (14 staff), work to invoice (5 customers), and the supplier
list, customer list and chart of accounts.

Deliberate problems planted for the agent to find (17 exceptions):
  1  Severnvale Office Supplies  SOS-20931 sent twice (PDF + email reminder): duplicate, second copy not posted
  2  Brindlecote IT Services     invoice email says "we have changed banks": bank details differ from supplier list
  3  Coalbrook Waste Services    CWS-40218 total £262.00, but £210.00 + £42.00 VAT = £252.00
  4  Hadley Brook Cleaning       charges £64.00 VAT but shows no VAT number (not VAT registered on our list)
  5  Norbridge Tool Supplies     VAT number GB 571 2240 71 fails the HMRC check digits ...
  6  Norbridge Tool Supplies     ... and is not on the supplier list (new supplier)
  7  Stirling Lane Packaging     SLP-10442 dated 26 Sep 2026, before the October period
  8  Marchmont Insurance         annual policy Oct 2026 – Sep 2027: prepayment to spread
  9  Card 4417 (Alex Morgan)     £126.00 Merecroft Tyre & Auto: no receipt
 10  Card 8802 (Ravi Shah)       £24.00 Stockframe Images: no receipt
 11  Card 4417                   Ember & Oak Café £43.40 on the card, receipt £38.40 (tip added)
 12  Ember & Oak Café            coded to Entertainment (client lunch): VAT not reclaimable
 13  Forgeway Trade Counter      receipt paid with card ending 1234, not a company card (expense claim?)
 14  Layoutly Inc                USD 14.99 software subscription: reverse charge VAT
 15  Parcelbay Marketplace       mixed order (cables, coffee, plant, phone stand): coding unclear
 16  Payroll                     Jordan Hale's net pay is £100.00 more than gross less deductions
 17  Castlegate Developments     needs a PO on every invoice; job J-2302 has none
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
COMPANY_ADDRESS = ["Unit 7, Example Business Park", "Telford TF3 0XX"]
COMPANY_EMAIL = "accounts@demo-company.example"


def vat(seven: str) -> str:
    n = make_gb_vat_number(seven)
    return f"GB {n[2:5]} {n[5:9]} {n[9:]}"


# ------------------------------------------------------------------ suppliers
S = {
    "severnvale": dict(name="Severnvale Office Supplies Ltd", ref="SEVERN01", account="Office supplies", code="S",
                       vat=vat("3124570"), sort="00-11-22", acct="10004417", terms=30, email="accounts@severnvale-office.example",
                       contact="Karen Wilde", phone="01632 960 118", address=["4 Mill Street", "Shrewsbury SY1 0XX"]),
    "brindlecote": dict(name="Brindlecote IT Services Ltd", ref="BRINDL01", account="Computer and IT costs", code="S",
                        vat=vat("2875316"), sort="00-33-44", acct="10027719", terms=14, email="billing@brindlecote-it.example",
                        contact="Dan Price", phone="01632 960 204", address=["The Old Forge, Station Road", "Wellington TF1 0XX"]),
    "wrekinlink": dict(name="Wrekinlink Telecom Ltd", ref="WREKIN01", account="Telephone and internet", code="S",
                       vat=vat("4410829"), sort="00-55-66", acct="10031552", terms=14, email="billing@wrekinlink.example",
                       contact="", phone="01632 960 311", address=["Suite 2, Exchange House", "Telford TF3 0XX"]),
    "midshire": dict(name="Midshire Power Direct Ltd", ref="MIDSHI01", account="Light, power and heating", code="S",
                     vat=vat("5539120"), sort="00-77-88", acct="10045630", terms=14, email="business@midshire-power.example",
                     contact="", phone="01632 960 402", address=["PO Box 9XX", "Stafford ST16 0XX"]),
    "quarrybank": dict(name="Quarrybank Fleet Fuels Ltd", ref="QUARRY01", account="Motor expenses", code="S",
                       vat=vat("3381204"), sort="00-12-34", acct="10052281", terms=30, email="cards@quarrybank-fuels.example",
                       contact="", phone="01632 960 517", address=["Depot 3, Quarry Lane", "Much Wenlock TF13 0XX"]),
    "hadley": dict(name="Hadley Brook Cleaning", ref="HADLEY01", account="Cleaning", code="O", vat="", sort="00-21-43",
                   acct="10060318", terms=14, email="jo@hadleybrook-cleaning.example", contact="Jo Mason",
                   phone="07700 900 214", address=["12 Brook Close", "Telford TF5 0XX"]),
    "coalbrook": dict(name="Coalbrook Waste Services Ltd", ref="COALBR01", account="Waste disposal", code="S",
                      vat=vat("6120385"), sort="00-43-65", acct="10071224", terms=30, email="accounts@coalbrook-waste.example",
                      contact="Steve Hollins", phone="01632 960 633", address=["Recycling Centre, Furnace Road", "Telford TF4 0XX"]),
    "kettlewell": dict(name="Kettlewell Payroll & Accounts Ltd", ref="KETTLE01", account="Accountancy fees", code="S",
                       vat=vat("2299618"), sort="00-65-87", acct="10083390", terms=14, email="payroll@kettlewell-pa.example",
                       contact="Priya Nair", phone="01632 960 745", address=["First Floor, 18 High Street", "Newport TF10 0XX"]),
    "marchmont": dict(name="Marchmont Insurance Brokers Ltd", ref="MARCHM01", account="Insurance", code="E",
                      vat="", sort="00-87-09", acct="10094471", terms=30, email="renewals@marchmont-insurance.example",
                      contact="", phone="01632 960 856", address=["2 Castle Gate", "Ludlow SY8 0XX"]),
    "dawbury": dict(name="Dawbury Print & Signs Ltd", ref="DAWBUR01", account="Advertising and marketing", code="S",
                    vat=vat("7754102"), sort="00-90-12", acct="10105517", terms=30, email="studio@dawbury-print.example",
                    contact="Mel Carter", phone="01632 960 967", address=["Unit 11, Printworks Yard", "Telford TF2 0XX"]),
    "stirling": dict(name="Stirling Lane Packaging Ltd", ref="STIRLI01", account="Purchases", code="S",
                     vat=vat("3307761"), sort="00-13-57", acct="10116623", terms=30, email="sales@stirlinglane-packaging.example",
                     contact="", phone="01632 960 078", address=["Stirling Lane", "Bridgnorth WV16 0XX"]),
    "madeley": dict(name="Madeley Van Hire Ltd", ref="MADELE01", account="Motor expenses", code="S",
                    vat=vat("4908815"), sort="00-24-68", acct="10127739", terms=30, email="hire@madeley-vans.example",
                    contact="", phone="01632 960 189", address=["Coalport Road", "Madeley TF7 0XX"]),
}
NORBRIDGE = dict(name="Norbridge Tool Supplies Ltd", vat_valid=vat("5712240"), phone="01632 960 290",
                 address=["Trade Park, Unit 5", "Wolverhampton WV10 0XX"], email="sales@norbridge-tools.example")
NORBRIDGE["vat"] = NORBRIDGE["vat_valid"][:-2] + f"{(int(NORBRIDGE['vat_valid'][-2:]) + 2) % 100:02d}"  # wrong check digits

CARDHOLDERS = {"4417": "Alex Morgan", "8802": "Ravi Shah"}

# ---------------------------------------------------------------------- PDFs


def _pdf(lines: list[tuple[str, str]], *, size=(595, 842), margin=50) -> bytes:
    """Tiny layout engine: (style, text) lines top to bottom; '|' splits columns."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, invariant=1)  # reproducible bytes
    width, height = size
    y = height - margin
    fonts = {"title": ("Helvetica-Bold", 18), "h": ("Helvetica-Bold", 11), "b": ("Helvetica-Bold", 9.5),
             "n": ("Helvetica", 9.5), "s": ("Helvetica", 8), "i": ("Helvetica-Oblique", 10), "big": ("Helvetica-Bold", 13)}
    for style, text in lines:
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
        cols = text.split("|")
        if len(cols) == 1:
            c.drawString(margin, y, text)
        else:
            usable = width - 2 * margin
            xs = [margin, margin + usable * 0.55, margin + usable * 0.68, margin + usable * 0.84] if len(cols) == 4 else \
                 [margin + usable * i / len(cols) for i in range(len(cols))]
            for i, (x, col) in enumerate(zip(xs, cols)):
                if i == 0:
                    c.drawString(x, y, col)
                else:
                    right = xs[i + 1] - 6 if i + 1 < len(xs) else width - margin
                    c.drawRightString(right, y, col)
        y -= sz + 5
    c.showPage()
    c.save()
    return buf.getvalue()


def money(v: float) -> str:
    return f"£{v:,.2f}"


def invoice_pdf(sup: dict, *, title: str, number: str, date: str, due: str | None, items: list[tuple], vat_summary: list[tuple],
                total: float | None = None, extra: list[str] = (), bank: tuple[str, str] | None = None,
                vat_number: str | None = None, terms: str = "", po: str = "") -> bytes:
    """items: (description, qty, unit, net, rate); vat_summary: (rate, net, vat)."""
    net = round(sum(i[3] for i in items), 2)
    vat_total = round(sum(v[2] for v in vat_summary), 2)
    total = round(net + vat_total, 2) if total is None else total
    vn = sup.get("vat", "") if vat_number is None else vat_number
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]] + [("n", f"Tel {sup['phone']} · {sup['email']}")]
    if vn:
        lines.append(("n", f"VAT Reg No: {vn}"))
    lines += [("gap", ""), ("title", title), ("gap", ""),
              ("n", f"{title.title()} number: {number}"), ("n", f"{'Invoice' if 'INVOICE' in title else 'Document'} date: {date}")]
    if due:
        lines.append(("n", f"Due date: {due}"))
    if po:
        lines.append(("n", f"Your order ref: {po}"))
    lines += [("gap", ""), ("b", "Invoice to:"), ("n", COMPANY)] + [("n", a) for a in COMPANY_ADDRESS] + [("gap", "")]
    lines += [("b", "Description|Qty|Unit price|Net"), ("rule", "")]
    for desc, qty, unit, line_net, rate in items:
        lines.append(("n", f"{desc} ({rate:g}% VAT)|{qty:g}|{money(unit)}|{money(line_net)}"))
    lines += [("rule", ""), ("n", f"Subtotal (net)|||{money(net)}")]
    for rate, vnet, vvat in vat_summary:
        lines.append(("n", f"VAT @ {rate:g}% on {money(vnet)}|||{money(vvat)}"))
    lines += [("b", f"Total due|||{money(total)}"), ("gap", "")]
    if terms:
        lines.append(("n", terms))
    if bank:
        lines.append(("n", f"Pay by bank transfer to {sup['name']}: sort code {bank[0]}, account number {bank[1]}. "
                           f"Quote {number}."))
    lines += [("s", e) for e in extra]
    return _pdf(lines)


def receipt_pdf(lines_in: list[str], notes: list[str] = ()) -> bytes:
    lines = [("b" if i == 0 else "n", t) for i, t in enumerate(lines_in)]
    lines += [("gap", "")] + [("i", n) for n in notes]
    return _pdf(lines, size=(260, 520), margin=18)

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

# ------------------------------------------------------------------ documents


def supplier_documents() -> dict[str, bytes]:
    docs: dict[str, bytes] = {}
    sv = S["severnvale"]
    sos_items = [("A4 copier paper 80gsm, box of 5 reams", 6, 22.40, 134.40, 20),
                 ("Black toner cartridge (compatible)", 1, 38.50, 38.50, 20),
                 ("Lever arch files, pack of 10", 1, 13.50, 13.50, 20)]
    sos = invoice_pdf(sv, title="INVOICE", number="SOS-20931", date="03/10/2026", due="02/11/2026", items=sos_items,
                      vat_summary=[(20, 186.40, 37.28)], bank=(sv["sort"], f"{sv['acct']}"), terms="Terms: 30 days net.")
    docs["2026-10-03_severnvale_SOS-20931.pdf"] = sos
    docs["2026-10-24_severnvale_payment-reminder.eml"] = eml(
        sender=f"{sv['contact']} <{sv['email']}>", subject="Copy invoice SOS-20931 - payment reminder", date="2026-10-24 09:12",
        body=f"Hello,\n\nPlease find attached a copy of invoice SOS-20931 dated 3 October for £223.68, which falls due on "
             f"2 November. Could you let me know when payment is scheduled?\n\nMany thanks,\n{sv['contact']}\n"
             f"Credit Control, {sv['name']}", attachment=("SOS-20931.pdf", sos))
    docs["2026-10-17_severnvale_CN-1187.pdf"] = invoice_pdf(
        sv, title="CREDIT NOTE", number="CN-1187", date="17/10/2026", due=None,
        items=[("Returned: black toner cartridge (damaged in transit)", 1, 38.50, 38.50, 20)],
        vat_summary=[(20, 38.50, 7.70)], extra=["Credit against invoice SOS-20877. This amount will be deducted from your account."])

    br = S["brindlecote"]
    bit = invoice_pdf(br, title="INVOICE", number="BIT-2026-1043", date="01/10/2026", due="15/10/2026",
                      items=[("Managed IT support - October 2026 (up to 15 users)", 1, 450.00, 450.00, 20)],
                      vat_summary=[(20, 450.00, 90.00)], bank=("00-99-01", "99990001"), terms="Terms: 14 days.")
    docs["2026-10-01_brindlecote_BIT-2026-1043.eml"] = eml(
        sender=f"Brindlecote IT Accounts <accounts-brindlecote@mailbox.example>", subject="Invoice BIT-2026-1043 - NEW BANK DETAILS",
        date="2026-10-01 16:47",
        body="Dear customer,\n\nPlease find attached your invoice for October's managed IT support.\n\n"
             "Please note we have changed banks. Please update your records and use the new details on the attached "
             "invoice for this and all future payments. Payment is due by 15 October.\n\nRegards,\nAccounts Team\n"
             "Brindlecote IT Services Ltd", attachment=("BIT-2026-1043.pdf", bit))

    wl = S["wrekinlink"]
    docs["2026-10-06_wrekinlink_WL-883412.pdf"] = invoice_pdf(
        wl, title="INVOICE", number="WL-883412", date="06/10/2026", due="20/10/2026",
        items=[("Business fibre broadband - October", 1, 65.00, 65.00, 20), ("Hosted phone system - 6 users", 6, 12.50, 75.00, 20),
               ("Call charges - September", 1, 2.50, 2.50, 20)],
        vat_summary=[(20, 142.50, 28.50)], terms="Paid by Direct Debit on or after 20/10/2026. No action needed.")

    mp = S["midshire"]
    docs["2026-10-09_midshire_MPD-5531872.pdf"] = invoice_pdf(
        mp, title="INVOICE", number="MPD-5531872", date="09/10/2026", due="23/10/2026",
        items=[("Electricity 01/09/2026-30/09/2026: day units 3,412 kWh @ 15.62p", 3412, 0.1562, 532.95, 20),
               ("Night units 640 kWh @ 9.84p", 640, 0.0984, 62.98, 20), ("Standing charge 30 days @ 54.74p", 30, 0.5474, 16.42, 20),
               ("Climate Change Levy 4,052 kWh @ 0.775p", 4052, 0.00775, 31.40, 20)],
        vat_summary=[(20, 643.75, 128.75)], bank=(mp["sort"], mp["acct"]), terms="Supply address: Unit 7, Example Business Park.")

    qf = S["quarrybank"]
    docs["2026-10-15_quarrybank_QFF-77120.pdf"] = invoice_pdf(
        qf, title="INVOICE", number="QFF-77120", date="15/10/2026", due="14/11/2026",
        items=[("Fuel card: diesel, 4 vans, 01-15 Oct (312.6 litres)", 1, 389.20, 389.20, 20)],
        vat_summary=[(20, 389.20, 77.84)], bank=(qf["sort"], qf["acct"]), terms="Fuel card account FC-2201. 30 days net.")

    hb = S["hadley"]
    docs["2026-10-31_hadley-brook_118.pdf"] = invoice_pdf(
        hb, title="INVOICE", number="118", date="31/10/2026", due="14/11/2026",
        items=[("Office cleaning - October (2 visits a week, 4 weeks)", 8, 40.00, 320.00, 20)],
        vat_summary=[(20, 320.00, 64.00)], bank=(hb["sort"], hb["acct"]), vat_number="",
        terms="Thank you for your business. Jo Mason, trading as Hadley Brook Cleaning.")

    cb = S["coalbrook"]
    docs["2026-10-14_coalbrook_CWS-40218.pdf"] = invoice_pdf(
        cb, title="INVOICE", number="CWS-40218", date="14/10/2026", due="13/11/2026",
        items=[("General waste 1100L bin - 4 lifts", 4, 38.50, 154.00, 20), ("Mixed recycling 1100L bin - 2 lifts", 2, 28.00, 56.00, 20)],
        vat_summary=[(20, 210.00, 42.00)], total=262.00, bank=(cb["sort"], cb["acct"]), terms="Waste transfer note WTN-8812 on file.")

    kw = S["kettlewell"]
    docs["2026-10-31_kettlewell_KPA-1192.pdf"] = invoice_pdf(
        kw, title="INVOICE", number="KPA-1192", date="31/10/2026", due="14/11/2026",
        items=[("Payroll bureau service - October (14 employees)", 14, 9.50, 133.00, 20),
               ("Auto-enrolment pension submissions", 1, 52.00, 52.00, 20)],
        vat_summary=[(20, 185.00, 37.00)], bank=(kw["sort"], kw["acct"]))

    mi = S["marchmont"]
    docs["2026-10-02_marchmont_MIB-66120.pdf"] = invoice_pdf(
        mi, title="INVOICE", number="MIB-66120", date="02/10/2026", due="01/11/2026",
        items=[("Commercial combined policy renewal, cover 01/10/2026 to 30/09/2027 - premium", 1, 1648.39, 1648.39, 0),
               ("Insurance Premium Tax at 12%", 1, 197.81, 197.81, 0)],
        vat_summary=[(0, 1846.20, 0.00)], bank=(mi["sort"], mi["acct"]), vat_number="",
        terms="Insurance premiums are exempt from VAT. Policy CC-4471-2026.")

    dp = S["dawbury"]
    docs["2026-10-20_dawbury_DPS-3307.pdf"] = invoice_pdf(
        dp, title="INVOICE", number="DPS-3307", date="20/10/2026", due="19/11/2026",
        items=[("A5 leaflets, full colour, 5,000", 1, 540.00, 540.00, 0), ("Vinyl van livery graphics, one van", 1, 180.00, 180.00, 20)],
        vat_summary=[(0, 540.00, 0.00), (20, 180.00, 36.00)], bank=(dp["sort"], dp["acct"]))

    sl = S["stirling"]
    docs["2026-09-26_stirling-lane_SLP-10442.pdf"] = invoice_pdf(
        sl, title="INVOICE", number="SLP-10442", date="26/09/2026", due="26/10/2026",
        items=[("Double-wall cartons 457x305x305mm, bundle of 25", 20, 38.00, 760.00, 20),
               ("Bubble wrap 750mm x 100m", 8, 35.00, 280.00, 20), ("Packing tape, case of 36 rolls", 4, 50.00, 200.00, 20)],
        vat_summary=[(20, 1240.00, 248.00)], bank=(sl["sort"], sl["acct"]), po="PO-0912")

    nb = dict(NORBRIDGE)
    docs["2026-10-22_norbridge_NTS-5521.pdf"] = invoice_pdf(
        nb, title="INVOICE", number="NTS-5521", date="22/10/2026", due="21/11/2026",
        items=[("Cordless drill driver 18V with 2 batteries", 1, 129.00, 129.00, 20), ("HSS drill bit set, 25 pieces", 2, 18.50, 37.00, 20),
               ("Safety glasses, box of 12", 1, 24.00, 24.00, 20)],
        vat_summary=[(20, 190.00, 38.00)], bank=("00-46-80", "10138845"), vat_number=nb["vat"],
        terms="New account - welcome! 30 days from invoice.")
    return docs


def card_documents() -> dict[str, bytes]:
    docs: dict[str, bytes] = {}
    docs["2026-10-02_trackfare_e-ticket.eml"] = eml(
        sender="TrackFare Rail Tickets <tickets@trackfare.example>", subject="Your e-ticket and receipt TF-88301245", date="2026-10-02 07:41",
        body="Thanks for booking with TrackFare.\n\nBooking reference: TF-88301245\nJourney: Telford Central to London Euston, "
             "return, travelling 2 October 2026\nPassenger: R. Shah\nTicket type: Off-Peak Return\n\nTotal paid: £64.50\n"
             "Paid with Visa card ending 8802\nRail fares are zero-rated for VAT (VAT £0.00).\n\nTrackFare Rail Tickets")
    docs["2026-10-03_wellington-road_fuel.pdf"] = receipt_pdf(
        ["WELLINGTON ROAD SERVICE STATION", "Wellington Road, Telford", f"VAT No {vat('6631045')}", "03/10/2026 08:14",
         "Pump 4 DIESEL 39.24 L @ 152.9p   £60.00", "TOTAL                 £60.00", "VAT @20%  net £50.00  VAT £10.00",
         "CARD ************4417   CONTACTLESS", "Receipt 004-118842", "THANK YOU"])
    docs["2026-10-06_kingfisher-lodge_booking.eml"] = eml(
        sender="Kingfisher Lodge Hotel <stay@kingfisher-lodge.example>", subject="Your invoice for booking KL-55120", date="2026-10-06 11:02",
        body=f"Dear Mr Shah,\n\nThank you for staying with us on 5 October 2026.\n\nInvoice KL-55120\nRoom only, 1 night "
             f"(Standard double)   £80.00\nVAT @ 20%   £16.00\nTotal   £96.00\nPaid in full by card ending 8802 on 06/10/2026.\n\n"
             f"Kingfisher Lodge Hotel, Birmingham B1 0XX · VAT Reg {vat('5013377')}")
    docs["2026-10-07_ember-and-oak_receipt.pdf"] = receipt_pdf(
        ["EMBER & OAK CAFÉ", "High Street, Telford", f"VAT No {vat('7120443')}", "07/10/2026 13:22  Table 6",
         "2 x Soup & sandwich     £22.80", "2 x Flat white          £8.20", "1 x Brownie             £4.75",
         "1 x Sparkling water     £2.65", "Net £32.00  VAT £6.40", "TOTAL                   £38.40",
         "Card ****4417  (tip added at terminal)", "Order 2214"],
        notes=["Handwritten on receipt: client lunch - Brightwater Facilities, contract review. AM"])
    docs["2026-10-08_parcelbay_order.eml"] = eml(
        sender="Parcelbay Marketplace <orders@parcelbay.example>", subject="Order confirmation PB-30-118845", date="2026-10-08 20:15",
        body=f"Thanks for your order, Ravi!\n\nOrder PB-30-118845 placed 8 October 2026\n\n2 x USB-C charging cable 2m "
             f"@ £8.99 = £17.98 (VAT 20%)\n1 x Coffee beans 1kg, medium roast = £14.50 (VAT 0%)\n1 x Desk plant in ceramic pot "
             f"= £18.95 (VAT 20%)\n1 x Adjustable phone stand = £6.50 (VAT 20%)\n\nItems total £57.93\nOf which VAT: £7.24 "
             f"(20% on £36.19 net); zero-rated £14.50\nPaid: £57.93 with card ending 8802\n\nSold by Parcelbay Retail Ltd, "
             f"VAT Reg {vat('2047719')}")
    docs["2026-10-13_layoutly_receipt.eml"] = eml(
        sender="Layoutly <billing@layoutly.example>", subject="Your Layoutly receipt #LY-2026-554120", date="2026-10-13 03:20",
        body="Receipt #LY-2026-554120\nDate: October 13, 2026\n\nLayoutly Pro, monthly plan (1 seat)   USD 14.99\n"
             "Tax   USD 0.00\nTotal paid   USD 14.99\nCharged to card ending 8802\n\nLayoutly Inc., 500 Market Street, "
             "San Francisco, CA, USA. Prices exclude any local taxes; business customers outside the US account for VAT themselves.")
    docs["2026-10-15_parcel-point_postage.pdf"] = receipt_pdf(
        ["PARCEL POINT TELFORD", "Town Centre counter", "15/10/2026 12:05", "Special delivery x 2       £15.70",
         "Signed for x 1             £2.75", "TOTAL                      £18.45", "Postal services are exempt from VAT",
         "Card ****4417", "Session 7741"])
    docs["2026-10-16_greenway_corner-shop.pdf"] = receipt_pdf(
        ["GREENWAY CORNER SHOP", "Greenway, Telford", "16/10/2026 08:47", "Semi-skimmed milk 4 pints   £2.45",
         "Tea bags 240                £4.20", "Digestive biscuits x 2      £3.20", "TOTAL                       £9.85",
         "VAT: all items zero rated", "Card ****8802"])
    docs["2026-10-20_wellington-road_fuel.pdf"] = receipt_pdf(
        ["WELLINGTON ROAD SERVICE STATION", "Wellington Road, Telford", f"VAT No {vat('6631045')}", "20/10/2026 17:32",
         "Pump 2 DIESEL 47.35 L @ 152.9p   £72.40", "TOTAL                 £72.40", "VAT @20%  net £60.33  VAT £12.07",
         "CARD ************4417   CHIP & PIN", "Receipt 004-121907"])
    docs["2026-10-21_trackfare_e-ticket.eml"] = eml(
        sender="TrackFare Rail Tickets <tickets@trackfare.example>", subject="Your e-ticket and receipt TF-88417730", date="2026-10-21 06:58",
        body="Thanks for booking with TrackFare.\n\nBooking reference: TF-88417730\nJourney: Telford Central to Birmingham "
             "New Street, return, travelling 21 October 2026\nPassenger: R. Shah\nTicket type: Anytime Day Return\n\n"
             "Total paid: £38.20\nPaid with Visa card ending 8802\nRail fares are zero-rated for VAT (VAT £0.00).\n\nTrackFare Rail Tickets")
    docs["2026-10-23_cloudnest_invoice.eml"] = eml(
        sender="CloudNest Hosting <billing@cloudnest.example>", subject="Invoice CN-INV-77310 (paid)", date="2026-10-23 00:05",
        body=f"Invoice CN-INV-77310 - PAID\nDate: 23/10/2026\nBill to: {COMPANY}\n\nWeb hosting, business plan - "
             f"November 2026   £15.00\nVAT @ 20%   £3.00\nTotal   £18.00\n\nPaid by card ending 8802. Thank you.\n"
             f"CloudNest Hosting Ltd · VAT Reg {vat('3906128')}")
    docs["2026-10-14_fixtrade_order.eml"] = eml(
        sender="Fixtrade Direct <orders@fixtrade.example>", subject="Order FD-447210 - VAT receipt", date="2026-10-14 10:33",
        body=f"Order FD-447210 - VAT receipt\nOrder date: 14/10/2026\n\n1 x Mitre saw blade 254mm 60T   £34.99\n"
             f"2 x Masonry drill bits set   £27.98\n1 x Heavy-duty extension reel 25m   £26.97\n\nTotal (inc VAT)   £89.94\n"
             f"Net £74.95, VAT £14.99\nPaid by card ending 4417 - collected in store\nFixtrade Direct Ltd, VAT Reg {vat('6650274')}")
    docs["2026-10-24_printdrop_invoice.eml"] = eml(
        sender="Printdrop Online <hello@printdrop.example>", subject="Your Printdrop VAT invoice PD-209981", date="2026-10-24 14:10",
        body=f"VAT invoice PD-209981 (paid)\nDate: 24/10/2026\nCustomer: {COMPANY}\n\nBusiness cards, 500, double-sided, "
             f"2 designs   £35.00\nVAT 20%   £7.00\nTotal paid   £42.00\nCard ending 8802\n\nPrintdrop Online Ltd · VAT Reg {vat('4471396')}")
    docs["2026-10-22_forgeway_trade-counter.pdf"] = receipt_pdf(
        ["FORGEWAY TRADE COUNTER", "Forgeway, Telford", f"VAT No {vat('5528830')}", "22/10/2026 16:05",
         "Wall plugs brown x 100      £5.99", "Wood screws 4x40 x 200      £11.98", "Silicone sealant clear x 3  £17.97",
         "Dust sheets x 2             £12.00", "Net £39.95  VAT £7.99", "TOTAL                       £47.94",
         "VISA DEBIT ****1234", "Receipt FT-55418"])
    return docs

# ---------------------------------------------------------------- spreadsheets


def card_statement() -> pd.DataFrame:
    rows = [
        ("02/10/2026", "8802", "TRACKFARE RAIL TICKETS", "64.50", "", ""),
        ("03/10/2026", "4417", "WELLINGTON RD SERVICE STN TELFORD", "60.00", "", ""),
        ("06/10/2026", "8802", "KINGFISHER LODGE HOTEL BIRMINGHAM", "96.00", "", ""),
        ("08/10/2026", "4417", "SQ *EMBER & OAK CAFE TELFORD", "43.40", "", ""),
        ("09/10/2026", "8802", "PARCELBAY MARKETPLACE", "57.93", "", ""),
        ("09/10/2026", "4417", "MERECROFT TYRE & AUTO", "126.00", "", ""),
        ("12/10/2026", "8802", "STOCKFRAME IMAGES", "24.00", "", ""),
        ("13/10/2026", "8802", "LAYOUTLY INC", "11.86", "USD", "14.99"),
        ("13/10/2026", "8802", "NON-STERLING TRANSACTION FEE", "0.33", "", ""),
        ("14/10/2026", "4417", "FIXTRADE DIRECT", "89.94", "", ""),
        ("15/10/2026", "4417", "PARCEL POINT TELFORD", "18.45", "", ""),
        ("16/10/2026", "8802", "GREENWAY CORNER SHOP", "9.85", "", ""),
        ("20/10/2026", "4417", "WELLINGTON RD SERVICE STN TELFORD", "72.40", "", ""),
        ("21/10/2026", "8802", "TRACKFARE RAIL TICKETS", "38.20", "", ""),
        ("23/10/2026", "8802", "CLOUDNEST HOSTING", "18.00", "", ""),
        ("24/10/2026", "8802", "PRINTDROP ONLINE", "42.00", "", ""),
        ("27/10/2026", "4417", "TELFORD CENTRE CAR PARK", "6.80", "", ""),
        ("30/10/2026", "", "PAYMENT RECEIVED - THANK YOU", "-1203.07", "", ""),
    ]
    return pd.DataFrame([{"Transaction Date": d, "Card ending": c, "Cardholder": CARDHOLDERS.get(c, ""), "Description": m,
                          "Amount (GBP)": a, "Original Currency": oc, "Original Amount": oa} for d, c, m, a, oc, oa in rows])


EMPLOYEES = [  # id, name, department, monthly gross, student loan
    ("E001", "Ravi Shah", "Office", 2950.00, 0), ("E002", "Hannah Pryce", "Office", 2150.00, 0),
    ("E003", "Tom Ellery", "Office", 1450.00, 0), ("E004", "Megan Doyle", "Office", 2050.00, 1),
    ("E005", "Alex Morgan", "Operations", 3250.00, 0), ("E006", "Craig Whitfield", "Operations", 2600.00, 0),
    ("E007", "Liam Barker", "Operations", 2450.00, 0), ("E008", "Jordan Hale", "Operations", 2380.00, 0),
    ("E009", "Sean Kirby", "Operations", 2420.00, 0), ("E010", "Ben Ashworth", "Operations", 2300.00, 0),
    ("E011", "Kyle Dunn", "Operations", 2280.00, 1), ("E012", "Owen Price", "Operations", 2500.00, 0),
    ("E013", "Laura Kemp", "Sales", 2850.00, 0), ("E014", "Daniel Fox", "Sales", 2700.00, 0),
]


def payroll_report() -> pd.DataFrame:
    rows = []
    for eid, name, dept, gross, sl in EMPLOYEES:
        paye = round(max(gross - 1047.50, 0) * 0.20, 2)
        ee_ni = round(max(gross - 1048.00, 0) * 0.08, 2)
        er_ni = round(max(gross - 416.67, 0) * 0.15, 2)
        ee_pen = round(max(gross - 520.00, 0) * 0.05, 2)
        er_pen = round(max(gross - 520.00, 0) * 0.03, 2)
        loan = round(max(gross - 2372.50, 0) * 0.09, 0) if sl else 0.0  # plan 2 threshold
        net = round(gross - paye - ee_ni - ee_pen - loan, 2)
        if name == "Jordan Hale":
            net = round(net + 100.00, 2)  # planted: net pay doesn't reconcile
        rows.append({"Employee ID": eid, "Employee Name": name, "Department": dept, "Gross Pay": gross, "PAYE Tax": paye,
                     "Employee NI": ee_ni, "Employee Pension": ee_pen, "Student Loan": loan, "Net Pay": net,
                     "Employer NI": er_ni, "Employer Pension": er_pen})
    df = pd.DataFrame(rows)
    total = {c: round(df[c].sum(), 2) for c in df.columns if c not in ("Employee ID", "Employee Name", "Department")}
    df = pd.concat([df, pd.DataFrame([{"Employee ID": "", "Employee Name": "TOTAL", "Department": "", **total}])], ignore_index=True)
    return df


def suppliers_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Supplier": s["name"], "Account Ref": s["ref"], "Default Account": s["account"], "Default VAT": s["code"],
                          "VAT Number": s["vat"], "Sort Code": s["sort"], "Account Number": s["acct"], "Terms (days)": s["terms"],
                          "Email": s["email"], "Contact": s["contact"]} for s in S.values()])


def customers_csv() -> pd.DataFrame:
    rows = [("Brightwater Facilities Ltd", "BRIGHT01", "ap@brightwater-fm.example", "Nadia Brooks", 30, "Yes", 10000),
            ("Lakeside Medical Practice", "LAKESI01", "practice.manager@lakeside-medical.example", "Helen Ward", 14, "No", 3000),
            ("Castlegate Developments Ltd", "CASTLE01", "purchase.ledger@castlegate-dev.example", "Mark Ellis", 30, "Yes", 15000),
            ("Redmoor Logistics Ltd", "REDMOO01", "accounts@redmoor-logistics.example", "Sam Patel", 30, "Yes", 5000),
            ("Oakhanger School Trust", "OAKHAN01", "finance@oakhanger-trust.example", "Claire Dawson", 30, "Yes", 8000)]
    return pd.DataFrame([{"Customer": n, "Account Ref": r, "Email": e, "Contact": c, "Terms (days)": t, "PO Required": p,
                          "Credit Limit": l} for n, r, e, c, t, p, l in rows])


def sales_csv() -> pd.DataFrame:
    rows = [("Brightwater Facilities Ltd", "28/10/2026", "J-2291", "BFL-PO-7734", "Planned maintenance visit, October", 4, 185.00, "S"),
            ("Brightwater Facilities Ltd", "28/10/2026", "J-2291", "BFL-PO-7734", "Replacement parts (as per job sheet)", 1, 96.40, "S"),
            ("Lakeside Medical Practice", "31/10/2026", "J-2296", "", "Service contract, October", 1, 420.00, "S"),
            ("Castlegate Developments Ltd", "24/10/2026", "J-2302", "", "Site works, 3 days", 3, 540.00, "S"),
            ("Castlegate Developments Ltd", "24/10/2026", "J-2302", "", "Materials supplied", 1, 312.75, "S"),
            ("Redmoor Logistics Ltd", "14/10/2026", "J-2305", "RL-55102", "Call-out and repair, 14 October", 1, 265.00, "S"),
            ("Redmoor Logistics Ltd", "14/10/2026", "J-2305", "RL-55102", "Additional labour (hours)", 3.5, 48.00, "S"),
            ("Oakhanger School Trust", "30/10/2026", "J-2310", "OST-2026-118", "Half-term works, 26 to 30 October (days)", 5, 410.00, "S")]
    return pd.DataFrame([{"Customer": c, "Completed": d, "Job": j, "Customer PO": po, "Description": desc, "Qty": q,
                          "Unit Price": p, "VAT Code": v} for c, d, j, po, desc, q, p, v in rows])


def chart_csv() -> pd.DataFrame:
    rows = [("4000", "Sales", "Income", ""), ("5000", "Purchases", "Cost of sales", "Packaging and materials used for customer work"),
            ("6000", "Wages and salaries", "Payroll", ""), ("6010", "Employer's NI", "Payroll", ""),
            ("6020", "Employer pension contributions", "Payroll", ""), ("6110", "Light, power and heating", "Expense", "Electricity and gas"),
            ("6120", "Cleaning", "Expense", "Office cleaning"), ("6130", "Waste disposal", "Expense", ""),
            ("6140", "Repairs and maintenance", "Expense", "Building repairs and small DIY materials (screws, sealant, fixings)"),
            ("6150", "Insurance", "Expense", ""), ("6200", "Telephone and internet", "Expense", ""),
            ("6210", "Computer and IT costs", "Expense", "IT support, web hosting, cables and small IT accessories"),
            ("6220", "Software subscriptions", "Expense", "Online software and apps"),
            ("6230", "Office supplies", "Expense", "Stationery, toner, small office items"),
            ("6240", "Postage and delivery", "Expense", ""), ("6300", "Motor expenses", "Expense", "Fuel, parking, van repairs and tyres"),
            ("6310", "Travel and accommodation", "Expense", "Rail fares and hotels"),
            ("6320", "Staff welfare", "Expense", "Tea, coffee, milk and small items for staff"),
            ("6330", "Entertainment", "Expense", "Client hospitality (VAT not reclaimable)"),
            ("6400", "Advertising and marketing", "Expense", "Printing, signage, business cards, stock images"),
            ("6410", "Tools and equipment", "Expense", "Small tools and equipment under £500"),
            ("6500", "Accountancy fees", "Expense", "Accountancy and payroll bureau fees"),
            ("6510", "Legal and professional fees", "Expense", ""), ("6600", "Bank charges", "Expense", "Card and bank fees"),
            ("1100", "Prepayments", "Current asset", ""), ("2100", "PAYE and NI payable", "Current liability", ""),
            ("2110", "Pension payable", "Current liability", ""), ("2120", "Net wages payable", "Current liability", ""),
            ("2130", "Other payroll deductions payable", "Current liability", ""),
            ("9999", "Suspense", "Suspense", "Use only when the right account is genuinely unclear")]
    return pd.DataFrame(rows, columns=["Account Code", "Account Name", "Account Type", "Notes"])

# --------------------------------------------------------------------- main


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()
    docs = {**supplier_documents(), **card_documents()}
    for name, data in docs.items():
        (INBOX / name).write_bytes(data)
    card_statement().to_csv(OUT / "company_card_statement_oct-2026.csv", index=False)
    payroll_report().to_csv(OUT / "payroll_summary_oct-2026.csv", index=False)
    suppliers_csv().to_csv(OUT / "supplier_list.csv", index=False)
    customers_csv().to_csv(OUT / "customer_list.csv", index=False)
    with pd.ExcelWriter(OUT / "work_to_invoice_oct-2026.xlsx", engine="xlsxwriter") as writer:
        sales_csv().to_excel(writer, index=False, sheet_name="Completed jobs")
        writer.book.set_properties({"created": datetime(2026, 11, 1, 9, 0)})  # reproducible bytes
    chart_csv().to_csv(OUT / "chart_of_accounts.csv", index=False)
    print(f"Wrote {len(docs)} documents to {INBOX} and 6 spreadsheets to {OUT}")
    print("Norbridge VAT number (invalid on purpose):", NORBRIDGE["vat"])


if __name__ == "__main__":
    main()

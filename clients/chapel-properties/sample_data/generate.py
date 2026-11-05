"""Generate the synthetic sample data for the Financial Data Entry Agent demo.

Everything here is invented: the company ("Demo Properties Ltd"), its seven
properties, the suppliers, amounts, VAT numbers and bank details. Bank sort
codes start 00- (not issued to any bank), phone numbers are Ofcom drama
numbers, postcodes end 0XX, email domains end .example. No real personal or
company data. Re-run to regenerate (byte-for-byte the same files):

    python clients/chapel-properties/sample_data/generate.py

October 2026 for a small property company near Ipswich. Inbox: 24 documents
(22 supplier invoices as PDF or email, one of them a second copy, 1 credit note
and 1 supplier statement): contractor repairs, building materials, cleaning and
gardening of common parts, safety certificates, landlord electricity and water,
the portfolio insurance renewal, a service charge demand for a leasehold flat,
letting agent fees and accountancy. Reference lists: supplier list (15
suppliers), chart of accounts, property register (7 properties + head office).

Deliberate problems planted for the agent to find (15 exceptions):
  1  Willowmere Grounds Maintenance  WGM-2210 email from a look-alike address says "we have changed banks":
                                     bank details differ from the supplier list
  2  Sallowfield Roofing             SR-1186 total £1,461.00, but £1,180.00 + £236.00 VAT = £1,416.00 (digits swapped)
  3  Clearflow Drainage              VAT number fails the HMRC check digits ...
  4  Clearflow Drainage              ... and is not on the supplier list (new supplier)
  5  Oakmere Kitchens & Joinery      not on the supplier list (new supplier) ...
  6  Oakmere Kitchens & Joinery      ... £5,820 kitchen replacement at 31 Heron Walk: repair or capital improvement?
                                     (Claude codes it with low confidence, so a person decides)
  7  G Lowe Property Maintenance     charges £68.00 VAT but shows no VAT number (not VAT registered on our list)
  8  Marlowe & Finch                 MF-7731 received twice (PDF, then an emailed copy with a reminder): duplicate
  9  Brightcote Electrical           BES-4471 dated 29 Sep 2026, before the October period
 10  Emberguard Fire & Gas Safety    EFS-2026-318 dated 2 Nov 2026 for work done on 28 Oct: after the period end
 11  Tallis & Penn Insurance         portfolio policy 1 Oct 2026 - 30 Sep 2027: prepayment to spread
 12  Harbourline Block Management    service charge for Flat 3 Quayside Court, Oct 2026 - Mar 2027: prepayment
 13  Corndell Building Supplies      statement lists CBS-54960 (£418.80), an invoice never received
 14  Corndell Building Supplies      statement shows CBS-55102 at £264.00; the invoice received is £246.00
 15  Turnwell Locks & Security       TLS-6120 says only "Flat 2", not which building: property unknown
"""

from __future__ import annotations

import hashlib
import sys
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

COMPANY = "Demo Properties Ltd"
COMPANY_ADDRESS = ["Office 2, Example House, 10 Sample Street", "Ipswich IP1 0XX"]
COMPANY_EMAIL = "accounts@demo-properties.example"


def vat(seven: str) -> str:
    n = make_gb_vat_number(seven)
    return f"GB {n[2:5]} {n[5:9]} {n[9:]}"


# ----------------------------------------------------------------- properties
PROPERTIES = [  # ref, name, site, keywords
    ("Granary Court", "Block of 6 flats, Ipswich", "2 Granary Lane", "Granary Court"),
    ("14 Lantern Row", "HMO, 5 rooms, bills included, Ipswich", "14 Lantern Row", ""),
    ("31 Heron Walk", "3-bed house, Ipswich", "31 Heron Walk", ""),
    ("Brickfield Yard", "3 commercial units, Ipswich", "Brickfield Yard", ""),
    ("8 Seagate Parade", "Shop with flat above, Felixstowe", "8 Seagate Parade", ""),
    ("3 Quayside Court", "Leasehold flat, Woodbridge", "Quayside Court", ""),
    ("22 Thistle Close", "2-bed house, Kesgrave, re-let from 1 Nov", "22 Thistle Close", ""),
    ("Head office", "Portfolio-wide costs and accounts", "", "Statement of account"),
]

# ------------------------------------------------------------------ suppliers
S = {
    "marlowe": dict(name="Marlowe & Finch Plumbing & Heating Ltd", ref="MARLOW01", account="Repairs and maintenance", code="S",
                    vat=vat("4127705"), sort="00-14-27", acct="20041127", terms=30, email="accounts@marlowefinch.example",
                    contact="Sue Finch", phone="01632 960 112", address=["Unit 4, Tannery Road", "Ipswich IP2 0XX"]),
    "brightcote": dict(name="Brightcote Electrical Services Ltd", ref="BRIGHT01", account="Repairs and maintenance", code="S",
                       vat=vat("3360912"), sort="00-25-38", acct="20052538", terms=30, email="office@brightcote-electrical.example",
                       contact="Dev Patel", phone="01632 960 245", address=["18 Foundry Lane", "Ipswich IP3 0XX"]),
    "sallowfield": dict(name="Sallowfield Roofing Ltd", ref="SALLOW01", account="Repairs and maintenance", code="S",
                        vat=vat("5208874"), sort="00-36-49", acct="20063649", terms=30, email="accounts@sallowfield-roofing.example",
                        contact="Mark Ellery", phone="01632 960 371", address=["The Yard, Coldfair Lane", "Felixstowe IP11 0XX"]),
    "willowmere": dict(name="Willowmere Grounds Maintenance Ltd", ref="WILLOW01", account="Grounds maintenance", code="S",
                       vat=vat("6631290"), sort="00-47-51", acct="20074751", terms=14, email="tom@willowmere-grounds.example",
                       contact="Tom Avery", phone="01632 960 428", address=["Willowmere Nursery, Back Lane", "Martlesham IP5 0XX"]),
    "spireview": dict(name="Spireview Cleaning Services Ltd", ref="SPIREV01", account="Cleaning", code="S",
                      vat=vat("2759031"), sort="00-58-62", acct="20085862", terms=30, email="hello@spireview-cleaning.example",
                      contact="Ana Costa", phone="01632 960 533", address=["9 Chantry Mews", "Ipswich IP2 0XX"]),
    "corndell": dict(name="Corndell Building Supplies Ltd", ref="CORNDE01", account="", code="S",
                     vat=vat("4482157"), sort="00-69-73", acct="20096973", terms=30, email="credit.control@corndell-supplies.example",
                     contact="Karen Webb", phone="01632 960 649", address=["Corndell Trade Park, Hadleigh Road", "Ipswich IP2 0XX"]),
    "northlight": dict(name="Northlight Energy Supply Ltd", ref="NORTHL01", account="Light, heat and power", code="S",
                       vat=vat("3915546"), sort="00-71-84", acct="20107184", terms=14, email="business@northlight-energy.example",
                       contact="", phone="01632 960 750", address=["PO Box 4XX", "Norwich NR1 0XX"]),
    "meadowbrook": dict(name="Meadowbrook Water Ltd", ref="MEADOW01", account="Water rates", code="Z",
                        vat=vat("6047728"), sort="00-82-95", acct="20118295", terms=28, email="billing@meadowbrook-water.example",
                        contact="", phone="01632 960 861", address=["Meadowbrook House", "Colchester CO1 0XX"]),
    "tallis": dict(name="Tallis & Penn Insurance Brokers Ltd", ref="TALLIS01", account="Insurance", code="E",
                   vat="", sort="00-93-06", acct="20129306", terms=30, email="renewals@tallispenn.example",
                   contact="Rachel Penn", phone="01632 960 972", address=["2 Corn Exchange Passage", "Bury St Edmunds IP33 0XX"]),
    "harbourline": dict(name="Harbourline Block Management Ltd", ref="HARBOU01", account="Service charges payable", code="E",
                        vat="", sort="00-15-26", acct="20131526", terms=30, email="service.charges@harbourline-bm.example",
                        contact="", phone="01632 960 083", address=["4 Quay Street", "Woodbridge IP12 0XX"]),
    "emberguard": dict(name="Emberguard Fire & Gas Safety Ltd", ref="EMBERG01", account="Safety certificates", code="S",
                       vat=vat("5574319"), sort="00-26-37", acct="20142637", terms=30, email="admin@emberguard-safety.example",
                       contact="Paul Kerr", phone="01632 960 194", address=["Unit 9, Ransome Court", "Ipswich IP3 0XX"]),
    "pellow": dict(name="Pellow & Grant Accountants Ltd", ref="PELLOW01", account="Accountancy fees", code="S",
                   vat=vat("2216843"), sort="00-37-48", acct="20153748", terms=14, email="office@pellowgrant.example",
                   contact="Helen Grant", phone="01632 960 205", address=["First Floor, 31 Museum Street", "Ipswich IP1 0XX"]),
    "glowe": dict(name="G Lowe Property Maintenance", ref="GLOWE01", account="Repairs and maintenance", code="O",
                  vat="", sort="00-48-59", acct="20164859", terms=14, email="gary@glowe-maintenance.example",
                  contact="Gary Lowe", phone="07700 900 316", address=["7 Pippin Close", "Kesgrave IP5 0XX"]),
    "turnwell": dict(name="Turnwell Locks & Security Ltd", ref="TURNWE01", account="Repairs and maintenance", code="S",
                     vat=vat("3870462"), sort="00-59-61", acct="20175961", terms=30, email="jobs@turnwell-locks.example",
                     contact="Lee Turner", phone="01632 960 327", address=["42 Wharf Street", "Ipswich IP4 0XX"]),
    "saltmarsh": dict(name="Saltmarsh Lettings Ltd", ref="SALTMA01", account="Letting agent fees", code="S",
                      vat=vat("4793385"), sort="00-61-72", acct="20186172", terms=14, email="landlords@saltmarsh-lettings.example",
                      contact="Jade Hollis", phone="01632 960 438", address=["11 Thoroughfare", "Woodbridge IP12 0XX"]),
}
# Not on the supplier list (new suppliers)
OAKMERE = dict(name="Oakmere Kitchens & Joinery Ltd", vat=vat("6102984"), phone="01632 960 549",
               address=["Oakmere Works, Mill Road", "Stowmarket IP14 0XX"], email="sales@oakmere-kitchens.example")
CLEARFLOW = dict(name="Clearflow Drainage Ltd", phone="07700 900 652", address=["3 Station Approach", "Ipswich IP2 0XX"],
                 email="jobs@clearflow-drainage.example")
_valid = vat("2958417")
CLEARFLOW["vat"] = _valid[:-2] + f"{(int(_valid[-2:]) + 3) % 100:02d}"  # wrong check digits, on purpose

# ---------------------------------------------------------------------- PDFs


def _pdf(lines: list[tuple[str, str]], *, size=(595, 842), margin=50) -> bytes:
    """Small layout helper: (style, text) lines from the top; '|' splits columns."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, invariant=1)  # reproducible bytes
    width, height = size
    y = height - margin
    fonts = {"title": ("Helvetica-Bold", 18), "b": ("Helvetica-Bold", 9.5), "n": ("Helvetica", 9.5),
             "s": ("Helvetica", 8), "i": ("Helvetica-Oblique", 9.5), "big": ("Helvetica-Bold", 13)}
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
            xs = [margin, margin + usable * 0.58, margin + usable * 0.70, margin + usable * 0.85]
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
    return f"{'-' if v < 0 else ''}£{abs(v):,.2f}"


def invoice_pdf(sup: dict, *, number: str, date: str, due: str | None, items: list[tuple], rate: float,
                title: str = "INVOICE", site: str = "", total: float | None = None, vat_override: float | None = None,
                vat_number: str | None = None, bank: tuple[str, str] | None = None, terms: str = "",
                extra: list[str] = ()) -> bytes:
    """items: (description, qty, unit price, net); one VAT rate per document."""
    net = round(sum(i[3] for i in items), 2)
    vat_amount = round(net * rate / 100, 2) if vat_override is None else vat_override
    total = round(net + vat_amount, 2) if total is None else total
    vn = sup.get("vat", "") if vat_number is None else vat_number
    kind = "Credit note" if "CREDIT" in title else ("Demand" if "DEMAND" in title else "Invoice")
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]] + [("n", f"Tel {sup['phone']} · {sup['email']}")]
    if vn:
        lines.append(("n", f"VAT Reg No: {vn}"))
    lines += [("gap", ""), ("title", title), ("gap", ""), ("n", f"{kind} number: {number}"), ("n", f"{kind} date: {date}")]
    if due:
        lines.append(("n", f"Due date: {due}"))
    lines += [("gap", ""), ("b", "Invoice to:"), ("n", COMPANY)] + [("n", a) for a in COMPANY_ADDRESS]
    if site:
        lines += [("gap", ""), ("b", site)]
    lines += [("gap", ""), ("b", "Description|Qty|Unit price|Net"), ("rule", "")]
    for desc, qty, unit, line_net in items:
        lines.append(("n", f"{desc}|{qty:g}|{money(unit)}|{money(line_net)}"))
    lines += [("rule", ""), ("n", f"Subtotal (net)|||{money(net)}"),
              ("n", f"VAT @ {rate:g}%|||{money(vat_amount)}" if rate else "VAT|||£0.00"),
              ("b", f"{'Total credit' if kind == 'Credit note' else 'Total due'}|||{money(total)}"), ("gap", "")]
    if terms:
        lines.append(("n", terms))
    if bank:
        lines.append(("n", f"Pay by bank transfer: sort code {bank[0]}, account number {bank[1]}. Quote {number}."))
    lines += [("s", e) for e in extra]
    return _pdf(lines)

# --------------------------------------------------------------------- emails


def eml(*, sender: str, subject: str, date: str, body: str, attachment: tuple[str, bytes] | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = COMPANY_EMAIL
    msg["Subject"] = subject
    msg["Date"] = format_datetime(pd.Timestamp(date).tz_localize("Europe/London").to_pydatetime())
    msg["Message-ID"] = f"<{hashlib.sha1((subject + date).encode()).hexdigest()[:16]}@mail.example>"
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
        msg.set_boundary("==demo-" + hashlib.sha1(subject.encode()).hexdigest()[:20])  # reproducible bytes
    return bytes(msg)

# ------------------------------------------------------------------ documents


def bank(sup: dict) -> tuple[str, str]:
    return sup["sort"], sup["acct"]


def documents() -> dict[str, bytes]:
    docs: dict[str, bytes] = {}

    br = S["brightcote"]
    docs["2026-09-29_brightcote_BES-4471.pdf"] = invoice_pdf(
        br, number="BES-4471", date="29/09/2026", due="29/10/2026", rate=20, bank=bank(br),
        site="Site: Granary Court, 2 Granary Lane, Ipswich",
        items=[("Replace failed emergency light fittings, communal stairwell", 2, 86.00, 172.00),
               ("Labour, testing and certificate", 1, 68.00, 68.00)], terms="Terms: 30 days.")

    tp = S["tallis"]
    docs["2026-10-01_tallis-penn_TPI-26-3381.pdf"] = invoice_pdf(
        tp, number="TPI-26-3381", date="01/10/2026", due="31/10/2026", rate=0, bank=bank(tp),
        items=[("Property owners' portfolio policy (7 properties), cover 01/10/2026 to 30/09/2027", 1, 4210.71, 4210.71),
               ("Insurance Premium Tax at 12%", 1, 505.29, 505.29)],
        terms="Insurance premiums are exempt from VAT. Policy POP-2210-2026, renewal for the year.")

    hb = S["harbourline"]
    docs["2026-10-01_harbourline_SC-2026-0427.pdf"] = invoice_pdf(
        hb, title="SERVICE CHARGE DEMAND", number="SC-2026-0427", date="01/10/2026", due="31/10/2026", rate=0, bank=bank(hb),
        site="Property: Flat 3, Quayside Court, Woodbridge",
        items=[("Half-yearly service charge in advance, 01/10/2026 to 31/03/2027", 1, 960.00, 960.00),
               ("Reserve fund contribution, 01/10/2026 to 31/03/2027", 1, 180.00, 180.00)],
        terms="Service charges are not subject to VAT. Payable in advance under the lease.",
        extra=["Issued on behalf of Quayside Court (Woodbridge) Management Company Ltd."])

    wm = S["willowmere"]
    wgm = invoice_pdf(wm, number="WGM-2210", date="02/10/2026", due="16/10/2026", rate=20, bank=("00-98-76", "99987601"),
                      site="Site: Granary Court, 2 Granary Lane, Ipswich",
                      items=[("Communal gardens: grass cutting, hedge trimming and leaf clearance, October", 1, 220.00, 220.00)],
                      terms="Terms: 14 days.")
    docs["2026-10-02_willowmere_WGM-2210.eml"] = eml(
        sender="Willowmere Grounds Accounts <willowmere.accounts@mailbox.example>", date="2026-10-02 17:52",
        subject="Invoice WGM-2210 - UPDATED BANK DETAILS",
        body="Good afternoon,\n\nPlease find attached our invoice for October's grounds maintenance at Granary Court.\n\n"
             "Please note we have moved to a new bank. Kindly update your records and use the account details on the "
             "attached invoice for this and all future payments. Payment is due by 16 October.\n\nMany thanks,\n"
             "Accounts, Willowmere Grounds Maintenance Ltd", attachment=("WGM-2210.pdf", wgm))

    mf = S["marlowe"]
    mf7731 = invoice_pdf(mf, number="MF-7731", date="03/10/2026", due="02/11/2026", rate=20, bank=bank(mf),
                         site="Job address: 14 Lantern Row, Ipswich",
                         items=[("Boiler breakdown call-out and labour (hours)", 2.5, 58.00, 145.00),
                                ("Diverter valve cartridge, supplied and fitted", 1, 140.00, 140.00)], terms="Terms: 30 days.")
    docs["2026-10-03_marlowe-finch_MF-7731.pdf"] = mf7731
    docs["2026-10-24_marlowe-finch_copy-invoice.eml"] = eml(
        sender=f"{mf['contact']} <{mf['email']}>", date="2026-10-24 10:05", subject="Copy invoice MF-7731 - reminder",
        body=f"Hello,\n\nJust a reminder that invoice MF-7731 dated 3 October for £342.00 (boiler repair at 14 Lantern Row) "
             f"falls due on 2 November. A copy is attached in case the original went astray.\n\nThanks,\n{mf['contact']}\n"
             f"{mf['name']}", attachment=("MF-7731.pdf", mf7731))
    docs["2026-10-27_marlowe-finch_MF-7790.pdf"] = invoice_pdf(
        mf, number="MF-7790", date="27/10/2026", due="26/11/2026", rate=20, bank=bank(mf),
        site="Job address: Unit 2, Brickfield Yard, Ipswich",
        items=[("Repair leaking WC cistern: labour (hours)", 1, 58.00, 58.00), ("Cistern fill valve", 1, 26.50, 26.50)],
        terms="Terms: 30 days.")

    nl = S["northlight"]
    docs["2026-10-05_northlight_NES-448120.pdf"] = invoice_pdf(
        nl, number="NES-448120", date="05/10/2026", due="19/10/2026", rate=5,
        site="Supply address: 14 Lantern Row, Ipswich (domestic supply)",
        items=[("Electricity 01/09/2026-30/09/2026: 1,046 kWh @ 24.50p", 1046, 0.245, 256.27),
               ("Standing charge 30 days @ 53.20p", 30, 0.532, 15.96)],
        terms="VAT at 5% (domestic). Paid by Direct Debit on or after 19/10/2026. No action needed.")
    docs["2026-10-06_northlight_NES-448377.pdf"] = invoice_pdf(
        nl, number="NES-448377", date="06/10/2026", due="20/10/2026", rate=20,
        site="Supply address: Granary Court landlord supply (communal lighting and door entry)",
        items=[("Electricity 01/09/2026-30/09/2026: 412 kWh @ 26.10p", 412, 0.261, 107.53),
               ("Standing charge 30 days @ 61.40p", 30, 0.614, 18.42),
               ("Climate Change Levy 412 kWh @ 0.775p", 412, 0.00775, 3.19)],
        terms="Paid by Direct Debit on or after 20/10/2026. No action needed.")

    eg = S["emberguard"]
    docs["2026-10-07_emberguard_EFS-2026-301.pdf"] = invoice_pdf(
        eg, number="EFS-2026-301", date="07/10/2026", due="06/11/2026", rate=20, bank=bank(eg),
        site="Site: 31 Heron Walk, Ipswich",
        items=[("Annual landlord gas safety check and certificate (CP12)", 1, 78.00, 78.00)], terms="Terms: 30 days.")
    docs["2026-11-02_emberguard_EFS-2026-318.pdf"] = invoice_pdf(
        eg, number="EFS-2026-318", date="02/11/2026", due="02/12/2026", rate=20, bank=bank(eg),
        site="Site: Granary Court, 2 Granary Lane, Ipswich",
        items=[("Six-monthly fire alarm and emergency lighting service, carried out 28/10/2026", 1, 185.00, 185.00)],
        terms="Terms: 30 days.")

    mw = S["meadowbrook"]
    docs["2026-10-08_meadowbrook_MW-55871.pdf"] = invoice_pdf(
        mw, number="MW-55871", date="08/10/2026", due="05/11/2026", rate=0, bank=bank(mw),
        site="Supply address: 14 Lantern Row, Ipswich",
        items=[("Water supply 01/07/2026-30/09/2026: 38 m3 @ £1.92", 38, 1.92, 72.96),
               ("Wastewater 01/07/2026-30/09/2026: 36 m3 @ £2.17", 36, 2.17, 78.12)],
        terms="Water and sewerage charges are zero-rated for VAT.")

    sr = S["sallowfield"]
    docs["2026-10-09_sallowfield_SR-1186.pdf"] = invoice_pdf(
        sr, number="SR-1186", date="09/10/2026", due="08/11/2026", rate=20, total=1461.00, bank=bank(sr),
        site="Site: 8 Seagate Parade, Felixstowe",
        items=[("Replace slipped and broken roof tiles, rear pitch", 1, 540.00, 540.00),
               ("Re-dress lead flashing at chimney", 1, 320.00, 320.00),
               ("Scaffold tower hire and erection, 1 week", 1, 320.00, 320.00)], terms="Terms: 30 days.")

    sc = S["spireview"]
    docs["2026-10-12_spireview_SCS-3092.pdf"] = invoice_pdf(
        sc, number="SCS-3092", date="12/10/2026", due="11/11/2026", rate=20, bank=bank(sc),
        site="Site: Granary Court, 2 Granary Lane, Ipswich",
        items=[("Communal area cleaning, October (weekly visits)", 4, 42.00, 168.00)], terms="Terms: 30 days.")

    cd = S["corndell"]
    acct = "Account: DEMO01. Terms: 30 days."
    docs["2026-10-13_corndell_CBS-55102.pdf"] = invoice_pdf(
        cd, number="CBS-55102", date="13/10/2026", due="12/11/2026", rate=20, bank=bank(cd),
        site="Delivered to: 22 Thistle Close, Kesgrave", terms=acct,
        items=[("Trade emulsion, white, 10L", 4, 28.50, 114.00), ("Satinwood, white, 2.5L", 2, 24.00, 48.00),
               ("Multi-purpose filler, 5kg", 2, 9.50, 19.00), ("Decorating sundries (rollers, trays, tape)", 1, 24.00, 24.00)])
    docs["2026-10-16_corndell_CBS-55187.pdf"] = invoice_pdf(
        cd, number="CBS-55187", date="16/10/2026", due="15/11/2026", rate=20, bank=bank(cd),
        site="Delivered to: 31 Heron Walk, Ipswich", terms=acct,
        items=[("Closeboard fence panel 1.8m x 1.8m", 6, 39.50, 237.00), ("Concrete fence post 2.4m", 3, 18.50, 55.50),
               ("Postcrete 20kg", 4, 5.00, 20.00)])
    docs["2026-10-20_corndell_CN-2291.pdf"] = invoice_pdf(
        cd, title="CREDIT NOTE", number="CN-2291", date="20/10/2026", due=None, rate=20,
        site="Collected from: 31 Heron Walk, Ipswich", terms=acct,
        items=[("Returned: closeboard fence panel 1.8m x 1.8m (surplus, from invoice CBS-55187)", 2, 39.50, 79.00)],
        extra=["This credit will be deducted from your account balance."])
    docs["2026-10-31_corndell_statement.pdf"] = statement_pdf(cd)

    tw = S["turnwell"]
    docs["2026-10-14_turnwell_TLS-6120.pdf"] = invoice_pdf(
        tw, number="TLS-6120", date="14/10/2026", due="13/11/2026", rate=20, bank=bank(tw),
        site="Job address: Flat 2 (tenant changeover). Ordered by phone.",
        items=[("Supply and fit euro cylinder lock, front door", 1, 65.00, 65.00), ("Keys cut", 3, 5.00, 15.00),
               ("Call-out", 1, 15.00, 15.00)], terms="Job ref TLS-J-8812. Terms: 30 days.")

    cf = CLEARFLOW
    docs["2026-10-15_clearflow_CD-0912.pdf"] = invoice_pdf(
        cf, number="CD-0912", date="15/10/2026", due="29/10/2026", rate=20, bank=("00-72-83", "20197283"),
        site="Job address: 14 Lantern Row, Ipswich",
        items=[("Emergency call-out: clear blocked foul drain (rodding and jetting)", 1, 165.00, 165.00)],
        terms="New customer - thank you. Payment within 14 days.")

    gl = S["glowe"]
    docs["2026-10-19_g-lowe_0412.pdf"] = invoice_pdf(
        gl, number="0412", date="19/10/2026", due="02/11/2026", rate=20, bank=bank(gl), vat_number="",
        site="Job: 22 Thistle Close, Kesgrave - empty property preparation",
        items=[("Patch and make good plaster (2 rooms), rehang 2 doors, reseal bath: labour (days)", 2, 150.00, 300.00),
               ("Materials", 1, 40.00, 40.00)], terms="Gary Lowe, trading as G Lowe Property Maintenance. 14 days please.")

    ok = OAKMERE
    docs["2026-10-21_oakmere_OKJ-1043.pdf"] = invoice_pdf(
        ok, number="OKJ-1043", date="21/10/2026", due="04/11/2026", rate=20, bank=("00-83-94", "20208394"),
        site="Site: 31 Heron Walk, Ipswich - kitchen replacement",
        items=[("Kitchen units (8 base and wall units), doors and handles", 1, 2640.00, 2640.00),
               ("Laminate worktops and upstands", 1, 560.00, 560.00),
               ("Strip out old kitchen, fit new kitchen, connect sink and hob", 1, 1450.00, 1450.00),
               ("Waste removal", 1, 200.00, 200.00)],
        terms="Layout as existing, with an integrated dishwasher added. Payment within 14 days.")

    sl = S["saltmarsh"]
    docs["2026-10-22_saltmarsh_SL-2207.pdf"] = invoice_pdf(
        sl, number="SL-2207", date="22/10/2026", due="05/11/2026", rate=20, bank=bank(sl),
        site="Property: 22 Thistle Close, Kesgrave (new tenancy from 01/11/2026)",
        items=[("Tenant find fee", 1, 650.00, 650.00), ("Inventory and check-in report", 1, 120.00, 120.00)],
        terms="Terms: 14 days.")

    pg = S["pellow"]
    docs["2026-10-30_pellow-grant_PG-5120.pdf"] = invoice_pdf(
        pg, number="PG-5120", date="30/10/2026", due="13/11/2026", rate=20, bank=bank(pg),
        items=[("Bookkeeping review and VAT return preparation, quarter to 30 September 2026", 1, 375.00, 375.00)],
        terms="Terms: 14 days.")
    return docs


def statement_pdf(sup: dict) -> bytes:
    rows = [("28/09/2026", "CBS-54960", "Invoice", 418.80), ("13/10/2026", "CBS-55102", "Invoice", 264.00),
            ("16/10/2026", "CBS-55187", "Invoice", 375.00), ("20/10/2026", "CN-2291", "Credit note", -94.80)]
    balance = round(sum(r[3] for r in rows), 2)
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]] + [("n", f"Tel {sup['phone']} · {sup['email']}"),
                                                                        ("n", f"VAT Reg No: {sup['vat']}"),
                                                                        ("gap", ""), ("title", "STATEMENT OF ACCOUNT"), ("gap", ""),
                                                                        ("n", "Statement date: 31/10/2026"), ("n", "Account: DEMO01"),
                                                                        ("gap", ""), ("b", "Account holder:"), ("n", COMPANY)]
    lines += [("n", a) for a in COMPANY_ADDRESS] + [("gap", ""), ("b", "Date|Reference|Type|Amount"), ("rule", "")]
    lines += [("n", f"{d}|{ref}|{kind}|{money(amount)}") for d, ref, kind, amount in rows]
    lines += [("rule", ""), ("b", f"Balance due|||{money(balance)}"), ("gap", ""),
              ("n", "Open items only. Invoice CBS-54960 is now overdue: please pay £418.80 by return."),
              ("n", f"Pay by bank transfer: sort code {sup['sort']}, account number {sup['acct']}. Quote account DEMO01.")]
    return _pdf(lines)

# --------------------------------------------------------------- spreadsheets


def suppliers_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Supplier": s["name"], "Account Ref": s["ref"], "Default Account": s["account"], "Default VAT": s["code"],
                          "VAT Number": s["vat"], "Sort Code": s["sort"], "Account Number": s["acct"], "Terms (days)": s["terms"],
                          "Email": s["email"], "Contact": s["contact"]} for s in S.values()])


def chart_csv() -> pd.DataFrame:
    rows = [
        ("200", "Rental income", "Income", "Rent from tenants"),
        ("210", "Service charge income", "Income", "Service charges recovered from tenants"),
        ("400", "Repairs and maintenance", "Property costs",
         "Reactive repairs and like-for-like replacements: plumbing, roofing, electrical, locks, drains, decorating, "
         "fencing and the materials for them"),
        ("410", "Cleaning", "Property costs", "Cleaning of common parts"),
        ("415", "Grounds maintenance", "Property costs", "Gardening and grounds for blocks and houses"),
        ("420", "Safety certificates", "Property costs",
         "Gas safety (CP12), electrical (EICR), fire alarm and emergency lighting servicing, legionella"),
        ("425", "Light, heat and power", "Property costs", "Landlord electricity and gas: common parts, HMOs, empty properties"),
        ("430", "Water rates", "Property costs", "Water and sewerage paid by the landlord"),
        ("435", "Council tax", "Property costs", "Council tax on empty properties and HMOs"),
        ("440", "Insurance", "Property costs", "Buildings and landlord insurance"),
        ("445", "Service charges payable", "Property costs",
         "Service charges and ground rent paid to freeholders and block managers on leasehold units"),
        ("450", "Letting agent fees", "Property costs", "Tenant find, inventories and management fees"),
        ("460", "Accountancy fees", "Overheads", ""),
        ("465", "Legal and professional fees", "Overheads", "Solicitors, surveyors, tenancy agreements"),
        ("470", "Office costs and software", "Overheads", ""),
        ("480", "Bank charges", "Overheads", ""),
        ("720", "Property improvements (capital)", "Fixed asset",
         "Work that improves or adds to a property (an extension, an upgraded specification): capitalised, not a repair"),
        ("620", "Prepayments", "Current asset", ""),
        ("820", "VAT", "Current liability", ""),
        ("999", "Suspense", "Suspense", "Use only when the right account is genuinely unclear"),
    ]
    return pd.DataFrame(rows, columns=["Account Code", "Account Name", "Account Type", "Notes"])


def properties_csv() -> pd.DataFrame:
    return pd.DataFrame(PROPERTIES, columns=["Property Ref", "Property Name", "Site", "Keywords"])

# --------------------------------------------------------------------- main


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()
    docs = documents()
    for name, data in docs.items():
        (INBOX / name).write_bytes(data)
    suppliers_csv().to_csv(OUT / "supplier_list.csv", index=False)
    chart_csv().to_csv(OUT / "chart_of_accounts.csv", index=False)
    properties_csv().to_csv(OUT / "property_register.csv", index=False)
    print(f"Wrote {len(docs)} documents to {INBOX} and 3 spreadsheets to {OUT}")
    print("Clearflow VAT number (invalid on purpose):", CLEARFLOW["vat"])


if __name__ == "__main__":
    main()

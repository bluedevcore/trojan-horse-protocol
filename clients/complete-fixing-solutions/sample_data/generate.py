"""Generate the synthetic sample data for the Timesheet-to-Payroll Agent demo.

Everything here is invented: the company ("Demo Fixings Ltd", a drylining,
partitions and ceilings subcontractor near Wrexham), its operatives, jobs,
main contractors, suppliers, amounts, VAT numbers and bank details. Bank sort
codes start 00- (not issued to any bank), phone numbers are Ofcom drama
numbers, email domains end .example. No real personal or company data.
Re-run to regenerate (the output is byte-for-byte reproducible):

    python clients/complete-fixing-solutions/sample_data/generate.py

The office's week: paper timesheets for the week commencing Monday 26 October
2026, keyed into a spreadsheet (95 lines for 18 operatives), checked on
Monday to Wednesday for the weekly payroll; plus October's supplier invoices
for materials and hire, reconciled against the purchase orders raised for
each job, then posted to Sage 50.

Files: weekly_timesheets_wc-26-oct-2026.xlsx, employee_list.csv (18 hourly
operatives), job_list.csv (7 jobs, one closed), purchase_orders_oct-2026.csv
(18 open POs), supplier_list.csv, chart_of_accounts.csv (Sage nominal codes)
and inbox/ (18 documents: 17 supplier invoices, one of them a second copy,
and 1 credit note, as PDF or email).

Deliberate problems planted for the agent to find (18 exceptions):
 Timesheets
  1  Rhys Talbot          new starter: 5 lines but not on the employee list (no starter paperwork yet)
  2  Kieran Molloy        Saturday 31 Oct overtime line not signed off by a supervisor
  3  Callum Rees          Wed 28 Oct: 07:30-15:30 on J-2601 and 14:00-18:00 on J-2614 overlap by 1.5 hours
  4  Sian Edwards         Thu 29 Oct line keyed twice (counted once)
  5  Aled Parry           Tue 27 Oct: "Hours" says 10, but 07:30-16:00 less 30 min is 8
  6  Josh Kendrick        Thu 29 Oct: 13.5 hours in one day (company limit 12)
  7  Liam Carney          Mon-Tue 17 hours booked to J-2588, a job closed on 16 October
  8  Huw Jarman           Fri 30 Oct booked to "J-2416", not on the job list (J-2614 transposed)
  9  Patryk Zielinski     on the employee list, but no timesheet this week
 Supplier invoices and purchase orders
 10  Clwyd Board & Stud   CBS-30871 received twice (post copy + emailed copy): duplicate, second copy not posted
 11  Clwyd Board & Stud   CBS-30922 (2nd delivery) takes PO-4404 to £6,440.00 against £6,250.00 ordered
 12  Alyn Access & Plant  AAP-7731 bills 3 weeks' scissor-lift hire (£960.00) against a 2-week PO-4406 (£640.00)
 13  Border Ceiling Sys.  BCS-11820 quotes PO-4471, which doesn't exist (PO-4417, same value, is awaiting invoice)
 14  Cestrian Tool Hire   CTH-09126 quotes PO-4412, which was raised with Alyn Access & Plant Hire
 15  Dee Valley Fixings   DVF-55187 emailed from a look-alike address with "new bank details"
 16  Pandy Timber & Sheet PTS-6604 total printed £1,152.60, but £948.00 + £189.60 VAT = £1,137.60
 17  Ridgeway Safety & Workwear  new supplier, not on the supplier list ...
 18  Ridgeway Safety & Workwear  ... and the invoice has no purchase order
Also included on purpose (no exception): an invoice with no PO number that
matches PO-4410 on supplier and amount, a credit note, a Saturday shift that
is signed off, and five POs still awaiting an invoice.
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

COMPANY = "Demo Fixings Ltd"
COMPANY_ADDRESS = ["Unit 4, Example Industrial Estate", "Wrexham LL13 0XX"]
COMPANY_EMAIL = "accounts@demo-fixings.example"


def vat(seven: str) -> str:
    n = make_gb_vat_number(seven)
    return f"GB {n[2:5]} {n[5:9]} {n[9:]}"

# ------------------------------------------------------------------ suppliers


S = {
    "deevalley": dict(name="Dee Valley Fixings Ltd", ref="DEEVAL01", account="Fixings and sundries", code="S",
                      vat=vat("4419027"), sort="00-14-27", acct="20031184", terms=30, email="accounts@deevalley-fixings.example",
                      contact="Nia Bowen", phone="01632 960 412", address=["Unit 12, Riverside Trade Park", "Chester CH4 0XX"]),
    "clwyd": dict(name="Clwyd Board & Stud Supplies Ltd", ref="CLWYDB01", account="Boards and studwork", code="S",
                  vat=vat("3870561"), sort="00-25-38", acct="20044617", terms=30, email="sales.ledger@clwyd-board.example",
                  contact="Gareth Lewis", phone="01632 960 523", address=["Station Yard, Mold Road", "Mold CH7 0XX"]),
    "alyn": dict(name="Alyn Access & Plant Hire Ltd", ref="ALYNAC01", account="Plant and access hire", code="S",
                 vat=vat("5160294"), sort="00-36-49", acct="20052290", terms=30, email="hire.accounts@alyn-access.example",
                 contact="Sara Jenkins", phone="01632 960 634", address=["Hire Depot, Bridge Street", "Wrexham LL13 0XX"]),
    "border": dict(name="Border Ceiling Systems Ltd", ref="BORDER01", account="Ceilings and grid", code="S",
                   vat=vat("6027713"), sort="00-47-50", acct="20068835", terms=30, email="credit.control@border-ceilings.example",
                   contact="Phil Tranter", phone="01632 960 745", address=["Unit 3, Canal Side", "Ellesmere SY12 0XX"]),
    "pandy": dict(name="Pandy Timber & Sheet Ltd", ref="PANDYT01", account="Timber and sheet materials", code="S",
                  vat=vat("2794408"), sort="00-58-61", acct="20073142", terms=30, email="office@pandy-timber.example",
                  contact="Elin Morgan", phone="01632 960 856", address=["Pandy Sawmill, Glyn Road", "Llangollen LL20 0XX"]),
    "bryn": dict(name="Bryn Skip & Waste Ltd", ref="BRYNSK01", account="Waste disposal and skips", code="S",
                 vat=vat("3315820"), sort="00-69-72", acct="20087356", terms=30, email="bookings@bryn-skips.example",
                 contact="", phone="01632 960 967", address=["Bryn Yard, Ruabon Road", "Wrexham LL14 0XX"]),
    "cestrian": dict(name="Cestrian Tool Hire Ltd", ref="CESTRI01", account="Plant and access hire", code="S",
                     vat=vat("4602139"), sort="00-70-83", acct="20091478", terms=30, email="accounts@cestrian-toolhire.example",
                     contact="Mark Doran", phone="01632 960 078", address=["45 Sealand Road", "Chester CH1 0XX"]),
    "pennant": dict(name="Pennant Fuel Cards Ltd", ref="PENNAN01", account="Motor fuel", code="S",
                    vat=vat("5583317"), sort="00-81-94", acct="20105524", terms=14, email="cards@pennant-fuel.example",
                    contact="", phone="01632 960 189", address=["Pennant House", "Oswestry SY11 0XX"]),
    "maelor": dict(name="Maelor Telecom Ltd", ref="MAELOR01", account="Telephone and internet", code="S",
                   vat=vat("6144029"), sort="00-92-05", acct="20116693", terms=14, email="billing@maelor-telecom.example",
                   contact="", phone="01632 960 290", address=["2 Bank Street", "Overton LL13 0XX"]),
}
RIDGEWAY = dict(name="Ridgeway Safety & Workwear Ltd", vat=vat("7038826"), sort="00-13-24", acct="20120071",
                email="orders@ridgeway-workwear.example", contact="Dan Shaw", phone="01632 960 301",
                address=["Unit 8, Ridgeway Court", "Warrington WA2 0XX"])
DEE_VALLEY_NEW_BANK = ("00-98-76", "98761234")  # the "new" details in the look-alike email

JOBS = [  # ref, name, main contractor, site, status
    ("J-2588", "Deeside Retail Park Unit 6 - partitions", "Halkyn Retail Developments Ltd", "Deeside Retail Park", "Closed 16/10/2026"),
    ("J-2601", "Wrexham Gateway student flats - drylining", "Gateway Living Developments Ltd", "Gateway Road, Wrexham", "Open"),
    ("J-2607", "Chester Business Quarter - office fit-out, floors 2-3", "Quarter Point Interiors Ltd", "City Road, Chester", "Open"),
    ("J-2610", "Mold community hospital - ward refurbishment", "Northbrook Healthcare Estates Ltd", "Mold", "Open"),
    ("J-2614", "Llay primary school extension - ceilings and partitions", "Marcher Construction Ltd", "Llay", "Open"),
    ("J-2619", "Gresford care home extension - drylining", "Ashgrove Care Homes Ltd", "Gresford", "Open"),
    ("YARD", "Yard, stores and van loading", COMPANY, "Wrexham", "Open"),
]
JOB_NAMES = {j[0]: j[1] for j in JOBS}

# ---------------------------------------------------------------------- PDFs


def _pdf(lines: list[tuple[str, str]], *, size=(595, 842), margin=48) -> bytes:
    """Minimal invoice layout: (style, text) lines top to bottom; '|' splits columns."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, invariant=1)  # reproducible bytes
    width, height = size
    y = height - margin
    fonts = {"title": ("Helvetica-Bold", 17), "h": ("Helvetica-Bold", 11), "b": ("Helvetica-Bold", 9.5),
             "n": ("Helvetica", 9.5), "s": ("Helvetica", 8), "big": ("Helvetica-Bold", 14)}
    for style, text in lines:
        if style == "gap":
            y -= 8
            continue
        if style == "rule":
            c.setStrokeColorRGB(0.72, 0.75, 0.8)
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
    return f"£{v:,.2f}"


def invoice_pdf(sup: dict, *, number: str, date: str, due: str | None, items: list[tuple], po: str = "", job: str = "",
                title: str = "INVOICE", total: float | None = None, bank: tuple[str, str] | None = None,
                notes: list[str] = ()) -> bytes:
    """items: (description, qty, unit price); every line is standard-rated (20% VAT)."""
    net = round(sum(round(q * u, 2) for _, q, u in items), 2)
    vat_amount = round(net * 0.20, 2)
    total = round(net + vat_amount, 2) if total is None else total
    bank = bank or (sup["sort"], sup["acct"])
    lines = [("big", sup["name"])] + [("n", a) for a in sup["address"]]
    lines += [("n", f"Tel {sup['phone']} · {sup['email']}"), ("n", f"VAT Reg No: {sup['vat']}"), ("gap", ""), ("title", title),
              ("gap", ""), ("n", f"{'Credit note' if 'CREDIT' in title else 'Invoice'} number: {number}"),
              ("n", f"{'Credit note' if 'CREDIT' in title else 'Invoice'} date: {date}")]
    if due:
        lines.append(("n", f"Due date: {due}"))
    if po:
        lines.append(("n", f"Your order no: {po}"))
    if job:
        lines.append(("n", f"Delivered to site / job ref: {job} {JOB_NAMES.get(job, '')}"))
    lines += [("gap", ""), ("b", "Invoice to:"), ("n", COMPANY)] + [("n", a) for a in COMPANY_ADDRESS] + [("gap", "")]
    lines += [("b", "Description|Qty|Unit price|Net"), ("rule", "")]
    for desc, qty, unit in items:
        lines.append(("n", f"{desc}|{qty:g}|{money(unit)}|{money(round(qty * unit, 2))}"))
    lines += [("rule", ""), ("n", f"Total net|||{money(net)}"), ("n", f"VAT @ 20% on {money(net)}|||{money(vat_amount)}"),
              ("b", f"{'Total credit' if 'CREDIT' in title else 'Total due'}|||{money(total)}"), ("gap", "")]
    if "CREDIT" not in title:
        lines.append(("n", f"Payment terms: 30 days. BACS to {sup['name']}, sort code {bank[0]}, account {bank[1]}."))
    lines += [("s", n) for n in notes]
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

DVF_55120 = [("Hammer-fix anchors 6x40mm, box of 100", 12, 14.20), ("Drywall screws 3.5x25mm, box of 1000", 20, 9.80),
             ("Drywall screws 3.5x38mm, box of 1000", 15, 11.60), ("M10 through bolts 10x100, box of 50", 6, 28.80),
             ("Low-modulus sealant, grey, 310ml", 48, 5.40), ("Steel angle bracket 90x90x65, pack of 25", 5, 42.80)]
CBS_30871 = [("Standard plasterboard 2400x1200x12.5mm", 240, 7.95), ("Acoustic plasterboard 2400x1200x15mm", 80, 14.40),
             ("C-stud 70mm x 3000mm", 300, 2.60), ("U-track 72mm x 3000mm", 50, 2.40)]
CBS_30922 = [("Standard plasterboard 2400x1200x12.5mm", 160, 7.95), ("C-stud 70mm x 3000mm", 320, 2.60),
             ("U-track 72mm x 3000mm", 60, 2.40), ("Easy-fill jointing compound 10kg", 16, 14.50)]
AAP_7702 = [("Aluminium tower scaffold, 4.2m platform - 1 week hire 05/10/2026 to 09/10/2026", 1, 295.00),
            ("Delivery and collection", 1, 90.00)]
AAP_7731 = [("Electric scissor lift 8m - hire 05/10/2026 to 23/10/2026 (3 weeks @ £280.00)", 3, 280.00),
            ("Delivery and collection", 1, 120.00)]
BCS_11794 = [("Main tee 3600mm, white", 120, 4.15), ("Cross tee 1200mm", 300, 1.32), ("Cross tee 600mm", 300, 0.68),
             ("Wall angle 3000mm", 80, 1.92), ("Mineral fibre ceiling tile 600x600, box of 16", 60, 16.05)]
BCS_11820 = [("Mineral fibre ceiling tile 600x600, box of 16", 72, 16.05), ("Hold-down clips, box of 500", 6, 21.40),
             ("Wire hangers 1.5m, pack of 100", 12, 19.00)]
BCS_11846 = [("MF ceiling primary channel 3600mm", 60, 5.10), ("MF ceiling section 3600mm", 140, 4.25),
             ("MF perimeter channel 3600mm", 40, 3.16), ("Soffit cleats, box of 100", 1, 49.00)]
PTS_6588 = [("CLS timber 38x63mm x 2.4m", 150, 2.45), ("WBP plywood 18mm 2440x1220", 10, 24.50)]
PTS_6604 = [("CLS timber 38x89mm x 3.0m", 120, 4.40), ("WBP plywood 12mm 2440x1220", 20, 21.00)]
DVF_55187 = [("Concrete screw anchors 7.5x80, box of 100", 8, 22.60),
             ("Wafer head screws 4.2x13 (stud to track), box of 1000", 10, 13.90),
             ("Acoustic intumescent sealant 310ml", 36, 7.25), ("Plasterboard adhesive, 25kg bag", 12, 13.50)]
DVF_55203 = [("Frame fixings 10x100, box of 50", 5, 17.35), ("Drywall screws 3.5x32mm, box of 1000", 20, 10.40),
             ("Galvanised noggin brackets, pack of 50", 4, 25.50)]
DVF_CN_0931 = [("Returned: M10 through bolts 10x100 (wrong length), box of 50", 3, 28.80)]
RSW_2208 = [("Hi-vis vest, orange, company print on back", 20, 3.95), ("Cut-resistant gloves level C, pair", 60, 3.20),
            ("Safety boots S3, assorted sizes", 6, 38.50), ("Safety glasses, clear", 24, 2.25)]
CTH_09126 = [("Mini tower scaffold 2.5m - 1 week hire 19/10/2026 to 23/10/2026", 1, 150.00), ("Delivery", 1, 30.00)]


def documents() -> dict[str, bytes]:
    d: dict[str, bytes] = {}
    dv, cb, al, bo, pa, br, ce = (S[k] for k in ("deevalley", "clwyd", "alyn", "border", "pandy", "bryn", "cestrian"))
    d["2026-10-02_dee-valley_DVF-55120.pdf"] = invoice_pdf(dv, number="DVF-55120", date="02/10/2026", due="01/11/2026",
                                                           items=DVF_55120, po="PO-4402", job="J-2601")
    cbs = invoice_pdf(cb, number="CBS-30871", date="05/10/2026", due="04/11/2026", items=CBS_30871, po="PO-4404",
                      job="J-2601", notes=["Delivery 1 of 2 against your order. Delivery note DN-77120."])
    d["2026-10-05_clwyd-board_CBS-30871.pdf"] = cbs
    d["2026-10-06_clwyd-board_CBS-30871-email.eml"] = eml(
        sender=f"{cb['contact']} <{cb['email']}>", subject="Invoice CBS-30871 - Demo Fixings Ltd", date="2026-10-06 08:42",
        body=f"Good morning,\n\nPlease find attached invoice CBS-30871 for the first delivery to Wrexham Gateway (your "
             f"order PO-4404). The original has also gone in the post.\n\nThanks,\n{cb['contact']}\nSales Ledger, {cb['name']}",
        attachment=("CBS-30871.pdf", cbs))
    d["2026-10-09_alyn-access_AAP-7702.pdf"] = invoice_pdf(al, number="AAP-7702", date="09/10/2026", due="08/11/2026",
                                                           items=AAP_7702, po="PO-4403", job="J-2607")
    d["2026-10-09_border-ceilings_BCS-11794.pdf"] = invoice_pdf(bo, number="BCS-11794", date="09/10/2026", due="08/11/2026",
                                                                items=BCS_11794, po="PO-4405", job="J-2614")
    d["2026-10-12_pandy-timber_PTS-6588.pdf"] = invoice_pdf(pa, number="PTS-6588", date="12/10/2026", due="11/11/2026",
                                                            items=PTS_6588, po="PO-4409", job="J-2619")
    d["2026-10-14_bryn-skip_BSW-20417.pdf"] = invoice_pdf(
        br, number="BSW-20417", date="14/10/2026", due="13/11/2026", job="J-2601",
        items=[("8-yard skip exchange, Gateway Road site (mixed construction waste)", 2, 120.00)],
        notes=["Waste transfer notes WTN-40871 and WTN-40902 available on request."])
    d["2026-10-16_dee-valley_DVF-CN-0931.pdf"] = invoice_pdf(
        dv, number="DVF-CN-0931", date="16/10/2026", due=None, items=DVF_CN_0931, job="J-2601", title="CREDIT NOTE",
        notes=["Credit against invoice DVF-55120: goods returned unused. This credit will be taken off your next payment."])
    d["2026-10-22_border-ceilings_BCS-11820.pdf"] = invoice_pdf(bo, number="BCS-11820", date="22/10/2026", due="21/11/2026",
                                                                items=BCS_11820, po="PO-4471", job="J-2614",
                                                                notes=["Phase 2 delivery, Llay school."])
    dvf = invoice_pdf(dv, number="DVF-55187", date="21/10/2026", due="20/11/2026", items=DVF_55187, po="PO-4415",
                      job="J-2607", bank=DEE_VALLEY_NEW_BANK)
    d["2026-10-21_dee-valley_DVF-55187.eml"] = eml(
        sender="Dee Valley Fixings Accounts <accounts@deevalley-fixings-uk.example>",
        subject="Invoice DVF-55187 - updated bank details", date="2026-10-21 17:58",
        body="Hello,\n\nPlease find attached invoice DVF-55187 for the fixings delivered to Chester Business Quarter.\n\n"
             "Please note we have moved our business banking. Kindly update your records and pay this and all future "
             "invoices to the new account shown on the attached invoice.\n\nKind regards,\nAccounts Department\n"
             "Dee Valley Fixings Ltd", attachment=("DVF-55187.pdf", dvf))
    d["2026-10-22_cestrian-tool-hire_CTH-09126.pdf"] = invoice_pdf(ce, number="CTH-09126", date="23/10/2026", due="22/11/2026",
                                                                   items=CTH_09126, po="PO-4412", job="J-2610")
    d["2026-10-23_clwyd-board_CBS-30922.pdf"] = invoice_pdf(cb, number="CBS-30922", date="23/10/2026", due="22/11/2026",
                                                            items=CBS_30922, po="PO-4404", job="J-2601",
                                                            notes=["Delivery 2 of 2 against your order. Delivery note DN-77388."])
    d["2026-10-26_pandy-timber_PTS-6604.pdf"] = invoice_pdf(pa, number="PTS-6604", date="26/10/2026", due="25/11/2026",
                                                            items=PTS_6604, po="PO-4413", job="J-2614", total=1152.60)
    rw = dict(RIDGEWAY)
    rsw = invoice_pdf(rw, number="RSW-2208", date="27/10/2026", due="26/11/2026", items=RSW_2208,
                      notes=["Delivered to: Demo Fixings Ltd yard, Example Industrial Estate."])
    d["2026-10-27_ridgeway-workwear_RSW-2208.eml"] = eml(
        sender=f"{rw['contact']} <{rw['email']}>", subject="Your order and invoice RSW-2208", date="2026-10-27 11:20",
        body="Hi,\n\nThanks for your telephone order on 23 October and welcome to Ridgeway. The PPE was delivered to your "
             "yard this morning and our invoice RSW-2208 is attached. We'll set up your account on 30-day terms.\n\n"
             f"Best wishes,\n{rw['contact']}\n{rw['name']}", attachment=("RSW-2208.pdf", rsw))
    d["2026-10-28_dee-valley_DVF-55203.pdf"] = invoice_pdf(dv, number="DVF-55203", date="28/10/2026", due="27/11/2026",
                                                           items=DVF_55203, po="PO-4418", job="J-2619")
    d["2026-10-29_border-ceilings_BCS-11846.pdf"] = invoice_pdf(bo, number="BCS-11846", date="29/10/2026", due="28/11/2026",
                                                                items=BCS_11846, po="PO-4411", job="J-2607")
    d["2026-10-30_alyn-access_AAP-7731.pdf"] = invoice_pdf(al, number="AAP-7731", date="30/10/2026", due="29/11/2026",
                                                           items=AAP_7731, po="PO-4406", job="J-2601")
    d["2026-10-30_bryn-skip_BSW-20488.pdf"] = invoice_pdf(br, number="BSW-20488", date="30/10/2026", due="29/11/2026",
                                                          items=[("6-yard skip delivery and exchange, Llay school site", 1, 150.00)],
                                                          po="PO-4416", job="J-2614")
    return d

# ---------------------------------------------------------------- spreadsheets


def purchase_orders() -> pd.DataFrame:
    rows = [
        ("PO-4402", "28/09/2026", "deevalley", "J-2601", "Anchors, drywall screws, through bolts, sealant, brackets", 1186.40),
        ("PO-4403", "30/09/2026", "alyn", "J-2607", "Tower scaffold 4.2m, 1 week hire from 05/10 + delivery/collection", 385.00),
        ("PO-4404", "01/10/2026", "clwyd", "J-2601", "Plasterboard, C-stud and U-track - 2 deliveries", 6250.00),
        ("PO-4405", "01/10/2026", "border", "J-2614", "Ceiling grid and mineral fibre tiles - phase 1", 2214.60),
        ("PO-4406", "02/10/2026", "alyn", "J-2601", "Scissor lift 8m, 2 weeks hire from 05/10 @ £260/wk + delivery/collection", 640.00),
        ("PO-4407", "05/10/2026", "clwyd", "J-2610", "Plasterboard and studwork - ward 3", 2870.00),
        ("PO-4408", "06/10/2026", "deevalley", "J-2610", "Fixings and sealant - ward 3", 468.20),
        ("PO-4409", "07/10/2026", "pandy", "J-2619", "CLS timber and 18mm ply", 612.50),
        ("PO-4410", "09/10/2026", "bryn", "J-2601", "2 x 8-yard skip exchanges", 240.00),
        ("PO-4411", "12/10/2026", "border", "J-2607", "MF ceiling channels, sections and cleats", 1076.40),
        ("PO-4412", "13/10/2026", "alyn", "J-2610", "Mini tower 2.5m, 1 week hire from 19/10 + delivery", 180.00),
        ("PO-4413", "14/10/2026", "pandy", "J-2614", "CLS timber 38x89 and 12mm ply", 948.00),
        ("PO-4414", "15/10/2026", "cestrian", "J-2619", "SDS drill and dust extractor, 1 week hire", 156.00),
        ("PO-4415", "16/10/2026", "deevalley", "J-2607", "Concrete anchors, wafer screws, intumescent sealant, adhesive", 742.80),
        ("PO-4416", "19/10/2026", "bryn", "J-2614", "6-yard skip delivery and exchange", 150.00),
        ("PO-4417", "19/10/2026", "border", "J-2614", "Ceiling tiles, clips and hangers - phase 2", 1512.00),
        ("PO-4418", "21/10/2026", "deevalley", "J-2619", "Frame fixings, drywall screws, noggin brackets", 396.75),
        ("PO-4419", "26/10/2026", "clwyd", "J-2619", "Plasterboard and studwork - first fix", 1940.00),
    ]
    return pd.DataFrame([{"PO Number": po, "PO Date": date, "Supplier": S[s]["name"], "Job": job, "Description": desc,
                          "Net Amount": f"{net:.2f}", "Raised By": "Office", "Status": "Open"}
                         for po, date, s, job, desc, net in rows])


EMPLOYEES = [  # id, name, team, hourly rate (contracted 40 h a week, overtime at time and a half)
    ("CF01", "Gethin Rowlands", "Supervisor", 19.50), ("CF02", "Ellis Vaughan", "Drylining", 17.20),
    ("CF03", "Callum Rees", "Drylining", 17.20), ("CF04", "Mared Pritchard", "Drylining", 17.20),
    ("CF05", "Dafydd Lloyd", "Drylining", 16.80), ("CF06", "Kieran Molloy", "Drylining", 16.80),
    ("CF07", "Tomasz Nowicki", "Drylining", 16.80), ("CF08", "Aled Parry", "Ceilings", 17.50),
    ("CF09", "Josh Kendrick", "Ceilings", 17.50), ("CF10", "Ryan Bellis", "Tape and joint", 16.40),
    ("CF11", "Siân Edwards", "Tape and joint", 16.40), ("CF12", "Marcus Doyle", "Labourer", 13.40),
    ("CF13", "Liam Carney", "Labourer", 13.40), ("CF14", "Huw Jarman", "Drylining", 17.20),
    ("CF15", "Bethan Morris", "Supervisor", 19.50), ("CF16", "Patryk Zielinski", "Drylining", 16.80),
    ("CF17", "Connor Whitley", "Labourer", 13.40), ("CF18", "Owain Bevan", "Ceilings", 17.50),
]

# day shapes: start, finish, break (mins)
A, B, C, F, SAT = ("07:30", "17:00", 30), ("07:30", "16:00", 30), ("08:00", "16:30", 30), ("07:30", "15:00", 30), ("08:00", "13:00", 0)
DAYS = ["26/10/2026", "27/10/2026", "28/10/2026", "29/10/2026", "30/10/2026"]
SATURDAY = "31/10/2026"


def _hours(start: str, finish: str, brk: int) -> float:
    s, f = (int(t[:2]) + int(t[3:]) / 60 for t in (start, finish))
    return round(f - s - brk / 60, 2)


def timesheets() -> pd.DataFrame:
    """One line per person per day (two when they moved site), as keyed from the paper sheets."""
    plan: list[tuple] = []  # (id, name, date, job, shape, signed, hours override)

    def week(eid, name, job, signed, shapes=(A, A, A, A, F), jobs=None):
        for i, (day, shape) in enumerate(zip(DAYS, shapes)):
            plan.append((eid, name, day, (jobs or [job] * 5)[i], shape, signed, None))

    ids = {n: e for e, n, *_ in EMPLOYEES}
    week("CF01", "Gethin Rowlands", "J-2601", "D Hughes")
    week("CF02", "Ellis Vaughan", "J-2601", "G Rowlands")
    # Callum Rees: moved from Wrexham Gateway to Llay school on Wednesday; the two lines overlap
    plan += [("CF03", "Callum Rees", DAYS[0], "J-2601", A, "G Rowlands", None),
             ("CF03", "Callum Rees", DAYS[1], "J-2601", A, "G Rowlands", None),
             ("CF03", "Callum Rees", DAYS[2], "J-2601", ("07:30", "15:30", 30), "G Rowlands", None),
             ("CF03", "Callum Rees", DAYS[2], "J-2614", ("14:00", "18:00", 0), "D Hughes", None),
             ("CF03", "Callum Rees", DAYS[3], "J-2614", B, "D Hughes", None),
             ("CF03", "Callum Rees", DAYS[4], "J-2614", F, "D Hughes", None)]
    week("CF04", "Mared Pritchard", "J-2610", "D Hughes", shapes=(B, B, B, B, F))
    week("CF05", "Dafydd Lloyd", "J-2601", "G Rowlands")
    week("CF06", "Kieran Molloy", "J-2607", "B Morris")
    plan.append(("CF06", "Kieran Molloy", SATURDAY, "J-2607", SAT, "", None))  # Saturday overtime, not signed off
    week("CF07", "Tomasz Nowicki", "J-2607", "B Morris")
    plan.append(("CF07", "Tomasz Nowicki", SATURDAY, "J-2607", SAT, "B Morris", None))
    week("CF08", "Aled Parry", "J-2614", "D Hughes", shapes=(B, B, B, B, F))
    week("CF09", "Josh Kendrick", "J-2614", "D Hughes", shapes=(A, A, A, ("06:00", "20:00", 30), F))
    week("CF10", "Ryan Bellis", "J-2601", "G Rowlands", shapes=(C, C, C, C, F))
    week("CF11", "Siân Edwards", "J-2607", "B Morris")
    week("CF12", "Marcus Doyle", "J-2601", "G Rowlands", shapes=(B, B, B, B, F),
         jobs=["J-2601", "J-2601", "J-2601", "J-2601", "YARD"])
    week("CF13", "Liam Carney", "J-2619", "D Hughes", shapes=(("07:30", "16:30", 30),) * 2 + (B, B, F),
         jobs=["J-2588", "J-2588", "J-2619", "J-2619", "J-2619"])  # Mon-Tue on a job closed on 16 October
    week("CF14", "Huw Jarman", "J-2610", "D Hughes", jobs=["J-2610"] * 4 + ["J-2416"])  # Friday: J-2614 transposed
    week("CF15", "Bethan Morris", "J-2607", "D Hughes")
    plan.append(("CF15", "Bethan Morris", SATURDAY, "J-2607", SAT, "D Hughes", None))
    week("CF17", "Connor Whitley", "J-2607", "B Morris", shapes=(B, B, B, B, F))
    week("CF18", "Owain Bevan", "J-2614", "D Hughes")
    week("", "Rhys Talbot", "J-2601", "G Rowlands", shapes=(B, B, B, B, F))  # new starter, not on the employee list
    assert ids.get("Patryk Zielinski") == "CF16" and not any(p[1] == "Patryk Zielinski" for p in plan)  # no timesheet

    rows = []
    for eid, name, day, job, (start, finish, brk), signed, override in plan:
        hours = _hours(start, finish, brk)
        if name == "Aled Parry" and day == DAYS[1]:
            hours = 10.0  # planted: keyed as 10, the times give 8
        rows.append({"Employee ID": eid, "Employee": name, "Date": day, "Job": job, "Start": start, "Finish": finish,
                     "Break (mins)": brk, "Hours": hours, "Signed Off By": signed})
        if name == "Siân Edwards" and day == DAYS[3]:
            rows.append(dict(rows[-1]))  # planted: the same line keyed twice
    return pd.DataFrame(rows)


def employees_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Employee ID": e, "Employee": n, "Team": t, "Hourly Rate": f"{r:.2f}", "Contracted Hours": 40,
                          "Overtime Rate": 1.5, "Pay Frequency": "Weekly"} for e, n, t, r in EMPLOYEES])


def jobs_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Job Ref": r, "Job Name": n, "Main Contractor": c, "Site": s, "Status": st}
                         for r, n, c, s, st in JOBS])


def suppliers_csv() -> pd.DataFrame:
    return pd.DataFrame([{"Supplier": s["name"], "Account Ref": s["ref"], "Default Nominal": s["account"],
                          "Default VAT": s["code"], "VAT Number": s["vat"], "Sort Code": s["sort"],
                          "Account Number": s["acct"], "Terms (days)": s["terms"], "Email": s["email"],
                          "Contact": s["contact"]} for s in S.values()])


def chart_csv() -> pd.DataFrame:
    rows = [("4000", "Sales - contract work", "Income", ""), ("4010", "Sales - day work and variations", "Income", ""),
            ("5000", "Boards and studwork", "Cost of sales", "Plasterboard, metal studs, track and partition materials"),
            ("5010", "Fixings and sundries", "Cost of sales", "Anchors, screws, bolts, adhesives, sealants, site sundries"),
            ("5020", "Ceilings and grid", "Cost of sales", "Suspended ceiling grid, tiles and MF ceiling sections"),
            ("5030", "Timber and sheet materials", "Cost of sales", "Timber, ply and sheet materials"),
            ("5100", "Plant and access hire", "Cost of sales", "Scissor lifts, towers and power tools on hire"),
            ("5200", "Waste disposal and skips", "Cost of sales", "Skip hire and waste transfer"),
            ("7000", "Gross wages - site operatives", "Payroll", ""), ("7006", "Employer's NI", "Payroll", ""),
            ("7010", "Gross wages - office", "Payroll", ""), ("7100", "Rent and rates", "Expense", "Yard and office"),
            ("7300", "Motor fuel", "Expense", "Van fuel cards"), ("7310", "Motor repairs and servicing", "Expense", "Vans"),
            ("7400", "Travel and site accommodation", "Expense", ""), ("7500", "Printing and stationery", "Expense", ""),
            ("7502", "Telephone and internet", "Expense", ""),
            ("7600", "Protective clothing and PPE", "Expense", "Hi-vis, boots, gloves, hard hats, eye and ear protection"),
            ("7610", "Small tools and equipment", "Expense", "Tools under £500 bought outright"),
            ("7700", "Training and site cards", "Expense", "CSCS cards and courses"),
            ("7800", "Repairs and maintenance", "Expense", "Yard and office repairs"), ("7900", "Bank charges", "Expense", ""),
            ("9998", "Suspense", "Suspense", "Use only when the right account is genuinely unclear")]
    return pd.DataFrame(rows, columns=["Nominal Code", "Account Name", "Account Type", "Notes"])

# --------------------------------------------------------------------- main


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()
    docs = documents()
    for name, data in docs.items():
        (INBOX / name).write_bytes(data)
    ts = timesheets()
    with pd.ExcelWriter(OUT / "weekly_timesheets_wc-26-oct-2026.xlsx", engine="xlsxwriter") as writer:
        ts.to_excel(writer, index=False, sheet_name="Week 44")
        writer.sheets["Week 44"].set_column(0, 8, 14)
        writer.book.set_properties({"created": datetime(2026, 11, 2, 8, 0)})  # reproducible bytes
    employees_csv().to_csv(OUT / "employee_list.csv", index=False)
    jobs_csv().to_csv(OUT / "job_list.csv", index=False)
    purchase_orders().to_csv(OUT / "purchase_orders_oct-2026.csv", index=False)
    suppliers_csv().to_csv(OUT / "supplier_list.csv", index=False)
    chart_csv().to_csv(OUT / "chart_of_accounts.csv", index=False)
    print(f"Wrote {len(docs)} documents to {INBOX}, {len(ts)} timesheet lines and 6 spreadsheets to {OUT}")


if __name__ == "__main__":
    main()

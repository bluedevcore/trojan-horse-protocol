"""Generate the synthetic sample data for the NFU Energy demo.

Everything here is invented: farm names, meter serials, readings and
deadlines. No real customer or personal data. Re-run to regenerate:

    python clients/nfu-energy/sample_data/generate.py

Deliberate problems planted for the checker to find (15 exceptions):
  1  S07 import meter      03 Sep  reading missing (kWh and register blank)
  2  S12 PV meter          17 Oct  kWh missing (register present)
  3  S13 import meter      14 Sep  negative advance −1,284 kWh (register went backwards)
  4  S10 PV meter          22 Aug  2,450 kWh on a 50 kWp array (decimal slip: register says 245)
  5  S09 import meter      05 Oct  loaded twice with different values (612.4 and 1,224.8)
  6  S16 import meter      19 Aug  loaded twice, identical (auto-resolved)
  7  S19 import meter      28 Sep  isolated spike ~6× normal (could be genuine)
  8  S06 heat meter        14 Aug  isolated spike ~4× normal in August
  9  S04 import meter      12–18 Sep no readings (7 days, comms outage)
 10  S17 heat meter        22–31 Oct no readings (data stops early)
 11  S03 heat meter        "31/09/2026" typed instead of 01/10 (invalid date) …
 12  S03 heat meter        … which also leaves 01 Oct with no reading
 13  S14 PV meter          08–16 Aug zero generation (inverter trip)
 14  S15 import meter      serial E17UP04521 in the export, register says E17UP04512
 15  S08 import meter      23 Oct daily kWh 562 but register advanced 652
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
START, END = pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-31")
DAYS = pd.date_range(START, END, freq="D")
rng = np.random.default_rng(20261105)

# --------------------------------------------------------------------- register
# meter_serial, site_id, site_name, town, postcode_district, meter_type, scheme, capacity, profile, base
IMPORT, PV, HEAT = "Electricity import", "Solar PV generation", "Biomass heat"
METERS = [
    ("E19UK08231", "S01", "Brookfield Farm", "Shipston-on-Stour", "CV36", IMPORT, "—", 100, "dairy", 420),
    ("G15PV03318", "S01", "Brookfield Farm", "Shipston-on-Stour", "CV36", PV, "FIT", 50, "pv", 0),
    ("E18UK11407", "S02", "Manor Farm Partnership", "Banbury", "OX17", IMPORT, "—", 150, "grain", 300),
    ("HM-2016-0412", "S02", "Manor Farm Partnership", "Banbury", "OX17", HEAT, "RHI", 199, "drying", 0),
    ("E20UK02958", "S03", "Hollins Green Poultry", "Market Drayton", "TF9", IMPORT, "—", 120, "flat", 650),
    ("HM-2015-0177", "S03", "Hollins Green Poultry", "Market Drayton", "TF9", HEAT, "RHI", 199, "poultry", 0),
    ("E16UK07720", "S04", "Westcombe Orchards", "Ledbury", "HR8", IMPORT, "—", 150, "coldstore", 620),
    ("G14PV01267", "S05", "Thornbury Dairy", "Leek", "ST13", PV, "FIT", 100, "pv", 0),
    ("HM-2017-0951", "S06", "Ashdown Glasshouses", "Chichester", "PO20", HEAT, "RHI", 500, "glasshouse", 0),
    ("E21UK00314", "S07", "Kingsmead Farm Shop & Café", "Stratford-upon-Avon", "CV37", IMPORT, "—", 60, "shop", 260),
    ("E17UK05562", "S08", "Long Acre Potatoes", "Spalding", "PE12", IMPORT, "—", 150, "store", 450),
    ("E19UK03391", "S09", "Redhill Pig Unit", "Driffield", "YO25", IMPORT, "—", 120, "flat", 700),
    ("G13PV00845", "S10", "Penrose Farm", "Truro", "TR4", PV, "FIT", 50, "pv", 0),
    ("HM-2016-0638", "S11", "Upper Wyke Farm", "Malton", "YO17", HEAT, "RHI", 199, "drying2", 0),
    ("G15PV02790", "S12", "Glebe Farm Holidays", "Bakewell", "DE45", PV, "FIT", 30, "pv", 0),
    ("E15UK09184", "S13", "Fenside Arable", "March", "PE15", IMPORT, "—", 100, "grain", 180),
    ("G16PV00412", "S14", "Bryn Mawr Farm", "Builth Wells", "LD2", PV, "FIT", 150, "pv", 0),
    ("E17UP04512", "S15", "Oakleigh Equestrian Centre", "Melton Mowbray", "LE14", IMPORT, "—", 60, "flat", 230),
    ("E18UK06673", "S16", "Hambleton Cereals Ltd", "Northallerton", "DL7", IMPORT, "—", 200, "grain", 400),
    ("HM-2018-0203", "S17", "Coldharbour Mushrooms", "Ashford", "TN26", HEAT, "RHI", 300, "flat_heat", 2200),
    ("G15PV04456", "S18", "Ellerby Free Range Eggs", "Pickering", "YO18", PV, "FIT", 250, "pv", 0),
    ("E20UK04419", "S19", "Mill Lane Dairy", "Nantwich", "CW5", IMPORT, "—", 200, "dairy", 480),
    ("E16UK10052", "S20", "Wolds Edge Farm", "Louth", "LN11", IMPORT, "—", 80, "flat", 350),
    ("G14PV03021", "S20", "Wolds Edge Farm", "Louth", "LN11", PV, "FIT", 40, "pv", 0),
]


def max_daily(meter_type: str, capacity: float) -> float:
    # Import: supply capacity (kVA) × 24 h. Heat: boiler kWth × 24 h.
    # PV: ~8 kWh per kWp per day is about the most a UK array can produce.
    return capacity * 8 if meter_type == PV else capacity * 24


def register_frame() -> pd.DataFrame:
    rows = []
    for serial, sid, name, town, pc, mtype, scheme, cap, *_ in METERS:
        rows.append({
            "meter_serial": serial, "site_id": sid, "site_name": name, "town": town, "postcode_district": pc,
            "meter_type": mtype, "scheme": scheme,
            "capacity": cap, "capacity_unit": {IMPORT: "kVA", PV: "kWp", HEAT: "kWth"}[mtype],
            "max_daily_kwh": max_daily(mtype, cap),
        })
    return pd.DataFrame(rows)

# ---------------------------------------------------------------------- profiles


def season(i: int) -> float:
    """0 at 1 Aug -> 1 at 31 Oct."""
    return i / (len(DAYS) - 1)


def daily_kwh(profile: str, base: float, cap: float, day: pd.Timestamp, i: int, lat_factor: float) -> float:
    noise = rng.normal(1.0, 0.07)
    t = season(i)
    if profile == "pv":
        clear_sky = (5.0 - 3.4 * t) * lat_factor  # kWh per kWp per day
        weather = rng.uniform(0.55, 1.0)
        return cap * clear_sky * weather
    if profile == "dairy":
        return base * (1 + 0.06 * t) * noise
    if profile == "grain":  # grain-drying fans during harvest (Aug to mid-Sep)
        harvest = 1.6 if day < pd.Timestamp("2026-09-15") else 1.0
        return base * harvest * noise
    if profile == "coldstore":  # apples go into store from mid-September
        return base * (1 + 0.5 * min(max((i - 40) / 20, 0), 1)) * noise
    if profile == "store":  # potato store cooling ramps up in autumn
        return base * (1 + 0.45 * t) * noise
    if profile == "shop":
        weekend = 1.25 if day.day_of_week >= 5 else 1.0
        return base * weekend * noise
    if profile == "flat":
        return base * noise
    if profile == "drying":  # biomass grain dryer + farmhouse
        return (2300 if day < pd.Timestamp("2026-09-12") else 600) * noise
    if profile == "drying2":
        return (2700 if day < pd.Timestamp("2026-09-18") else 320) * noise
    if profile == "glasshouse":  # heating demand rises into autumn
        return (850 + 2600 * t ** 1.6) * noise
    if profile == "flat_heat":
        return base * noise
    if profile == "poultry":  # 38-day broiler crop then ~8-day clean-out
        cycle = (i + 12) % 46
        if cycle >= 38:
            return 90 * noise
        return (3100 - 2300 * cycle / 37) * noise
    raise ValueError(profile)


LATITUDE = {"TR4": 1.12, "PO20": 1.08, "LD2": 1.0, "ST13": 0.97, "DE45": 0.96, "YO18": 0.93, "CV36": 1.02, "LN11": 0.95}

# ----------------------------------------------------------------------- build


def build() -> dict[str, pd.DataFrame]:
    series = {}
    for serial, sid, name, town, pc, mtype, scheme, cap, profile, base in METERS:
        vals = [round(max(daily_kwh(profile, base, cap, d, i, LATITUDE.get(pc, 1.0)), 0.0), 1) for i, d in enumerate(DAYS)]
        series[serial] = pd.DataFrame({"meter_serial": serial, "date": DAYS, "kwh": vals, "type": mtype})

    # --- planted problems that change the values themselves
    def at(serial, day):
        df = series[serial]
        return df.index[df["date"] == pd.Timestamp(day)][0]

    s = series["G16PV00412"]; s.loc[(s.date >= "2026-08-08") & (s.date <= "2026-08-16"), "kwh"] = 0.0  # 13 inverter trip
    s = series["E20UK04419"]; s.loc[at("E20UK04419", "2026-09-28"), "kwh"] = 2940.0  # 7 spike
    s = series["HM-2017-0951"]; s.loc[at("HM-2017-0951", "2026-08-14"), "kwh"] = 3900.0  # 8 spike
    s = series["E15UK09184"]; s.loc[at("E15UK09184", "2026-09-14"), "kwh"] = -1284.0  # 3 negative advance

    # cumulative registers (start values are arbitrary)
    for k, (serial, *_rest) in enumerate(METERS):
        df = series[serial]
        df["register"] = (10000 + 7919 * k * 13) % 900000 + df["kwh"].cumsum()
        df["register"] = df["register"].round(1)

    # --- planted problems in the exported values (register stays truthful)
    s = series["G13PV00845"]; i = at("G13PV00845", "2026-08-22")
    s.loc[i, "kwh"] = 245.0; s["register"] = (s["register"].iloc[0] - s["kwh"].iloc[0] + s["kwh"].cumsum()).round(1)
    s.loc[i, "kwh"] = 2450.0  # 4 decimal slip in the export only
    s = series["E17UK05562"]; i = at("E17UK05562", "2026-10-23")
    s.loc[i, "kwh"] = 652.0; s["register"] = (s["register"].iloc[0] - s["kwh"].iloc[0] + s["kwh"].cumsum()).round(1)
    s.loc[i, "kwh"] = 562.0  # 15 transposed digits

    s = series["E21UK00314"]; s.loc[at("E21UK00314", "2026-09-03"), ["kwh", "register"]] = np.nan  # 1 missing
    s = series["G15PV02790"]; s.loc[at("G15PV02790", "2026-10-17"), "kwh"] = np.nan  # 2 missing kWh only
    return series


def export_files(series: dict[str, pd.DataFrame]) -> None:
    def frame(serials):
        return pd.concat([series[s] for s in serials], ignore_index=True)

    # ---- 1. Electricity import: AMR/supplier daily export (CSV, ISO dates)
    imp = frame([m[0] for m in METERS if m[5] == IMPORT])
    imp = imp[~((imp.meter_serial == "E16UK07720") & imp.date.between("2026-09-12", "2026-09-18"))]  # 9 comms gap
    imp.loc[imp.meter_serial == "E17UP04512", "meter_serial"] = "E17UP04521"  # 14 serial typo
    dup_exact = imp[(imp.meter_serial == "E18UK06673") & (imp.date == "2026-08-19")]  # 6 identical duplicate
    dup_conf = imp[(imp.meter_serial == "E19UK03391") & (imp.date == "2026-10-05")].copy()  # 5 conflicting duplicate
    dup_conf["kwh"] = (dup_conf["kwh"] * 2).round(1)
    imp = pd.concat([imp, dup_exact, dup_conf]).sort_values(["meter_serial", "date"], kind="stable")
    out = pd.DataFrame({
        "MSN": imp.meter_serial,
        "Read Date": imp.date.dt.strftime("%Y-%m-%d"),
        "Register Read (kWh)": imp.register.map(lambda v: "" if pd.isna(v) else f"{v:.1f}"),
        "Daily kWh": imp.kwh.map(lambda v: "" if pd.isna(v) else f"{v:,.1f}"),  # thousands separators, as exported
        "Read Type": "A",
    })
    out.to_csv(OUT / "electricity_import_daily_aug-oct-2026.csv", index=False)

    # ---- 2. Solar PV generation meters: monitoring portal export (XLSX, real dates)
    pv = frame([m[0] for m in METERS if m[5] == PV])
    pd.DataFrame({
        "Generation Meter Serial": pv.meter_serial,
        "Date": pv.date,
        "Meter Reading (kWh)": pv.register,
        "Generation (kWh)": pv.kwh,
    }).to_excel(OUT / "solar_pv_generation_aug-oct-2026.xlsx", index=False, sheet_name="Generation")

    # ---- 3. Biomass heat meters: data logger export (CSV, UK dates dd/mm/yyyy)
    heat = frame([m[0] for m in METERS if m[5] == HEAT])
    heat = heat[~((heat.meter_serial == "HM-2018-0203") & (heat.date >= "2026-10-22"))]  # 10 data stops early
    dates = heat.date.dt.strftime("%d/%m/%Y")
    dates[(heat.meter_serial == "HM-2015-0177") & (heat.date == "2026-10-01")] = "31/09/2026"  # 11 + 12
    pd.DataFrame({
        "Heat Meter ID": heat.meter_serial,
        "Reading Date": dates,
        "Cumulative Heat (kWh)": heat.register.round(1),
        "Heat Output (kWh)": heat.kwh.round(1),
    }).to_csv(OUT / "biomass_heat_meters_aug-oct-2026.csv", index=False)


def reporting_calendar() -> pd.DataFrame:
    """Illustrative recurring obligations (dates invented for the demo)."""
    q = ("01/08/2026", "31/10/2026")
    rows = [
        ("Supplier consumption & bill validation report — September", "Energy suppliers", "Sep 2026",
         ("01/09/2026", "30/09/2026"), IMPORT, "12/10/2026", "Data team", "09/10/2026"),
        ("Monthly energy report to member farms — October", "Member farms", "Oct 2026",
         ("01/10/2026", "31/10/2026"), "All", "07/11/2026", "Account managers", ""),
        ("FIT generation meter readings to FIT licensees", "FIT licensees (energy suppliers)", "Aug–Oct 2026",
         q, PV, "10/11/2026", "Data team", ""),
        ("Supplier consumption & bill validation report — October", "Energy suppliers", "Oct 2026",
         ("01/10/2026", "31/10/2026"), IMPORT, "12/11/2026", "Data team", ""),
        ("Quarterly meter data quality sign-off", "Internal (operations manager)", "Aug–Oct 2026",
         q, "All", "13/11/2026", "Data team", ""),
        ("Climate Change Levy relief evidence pack (illustrative)", "HMRC (via suppliers)", "Aug–Oct 2026",
         q, IMPORT, "27/11/2026", "Compliance", ""),
        ("Non-Domestic RHI periodic data (heat meter readings)", "Ofgem", "Aug–Oct 2026",
         q, HEAT, "30/11/2026", "Data team", ""),
    ]
    return pd.DataFrame([
        {"obligation": o, "recipient": r, "period": p, "period_start": ps, "period_end": pe, "scope": sc,
         "due_date": d, "owner": ow, "submitted_on": sub}
        for o, r, p, (ps, pe), sc, d, ow, sub in rows
    ])


def main() -> None:
    register_frame().to_csv(OUT / "site_register.csv", index=False)
    export_files(build())
    reporting_calendar().to_csv(OUT / "reporting_calendar.csv", index=False)
    print("Wrote sample data to", OUT)


if __name__ == "__main__":
    main()

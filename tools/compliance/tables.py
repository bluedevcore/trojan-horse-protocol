"""Structured inputs (CSV / Excel): the register roles, their column aliases,
and routing of uploaded files - and of each sheet in a workbook - to a role.

A role is a kind of table the engine understands (an action log, a risk
register, a training matrix...). Column headings are matched to canonical
names ignoring case and punctuation. Columns the engine does not know are
kept under their own heading, so an updated register can be written back in
the client's own layout. A client config adds aliases or renames a table
under ``tables.<role>`` without code changes.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from tools.data_validation.loader import DataFileError, coerce_dates, coerce_numeric

__all__ = ["DataFileError", "TableSpec", "TABLE_SPECS", "LoadedTable", "table_spec", "load_table", "read_sheets",
           "detect_role", "route_upload", "norm"]


@dataclass
class TableSpec:
    role: str
    label: str
    required: list[str]
    aliases: dict[str, list[str]] = field(default_factory=dict)
    numeric: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)  # at least one must be present for upload routing
    sheet_words: list[str] = field(default_factory=list)  # sheet / file names that suggest this role


def _spec(role, label, required, aliases, numeric=(), dates=(), hints=(), sheet_words=()) -> TableSpec:
    return TableSpec(role, label, list(required), aliases, list(numeric), list(dates), list(hints), list(sheet_words))


_ID = ["ID", "Ref", "Reference", "Ref No", "Reference No", "No", "Number"]
_OWNER = ["Owner", "Responsible", "Responsible Person", "Assigned To", "Lead", "Accountable"]
_DEPT = ["Department", "Dept", "Team", "Function", "Business Area", "Area"]
_STATUS = ["Status", "Current Status", "State", "RAG Status"]

TABLE_SPECS: dict[str, TableSpec] = {s.role: s for s in [
    _spec("actions", "action log", ["id", "title"], {
        "id": ["Action ID", "Action Ref", "Action No", "Finding Ref", "CAPA Ref", *_ID],
        "title": ["Action", "Action Description", "Description", "Title", "Action Required", "Finding"],
        "department": _DEPT,
        "owner": ["Action Owner", *_OWNER],
        "raised": ["Date Raised", "Raised", "Opened", "Date Opened", "Created", "Date Logged"],
        "due": ["Due Date", "Target Date", "Due", "Deadline", "Current Due Date", "Revised Due Date", "Target"],
        "original_due": ["Original Due Date", "Original Target Date", "Original Due", "First Due Date"],
        "status": _STATUS,
        "last_update": ["Last Update", "Last Updated", "Date of Last Update", "Updated", "Last Update Date"],
        "update_note": ["Latest Update", "Update", "Progress", "Progress Notes", "Comments", "Notes"],
        "evidence": ["Evidence", "Evidence Ref", "Evidence Reference", "Closure Evidence", "Evidence Link"],
        "source": ["Source", "Raised From", "Origin", "Raised By", "Audit / Source"],
        "priority": ["Priority", "Severity", "Grade", "Finding Grade"],
        "linked_risk": ["Linked Risk", "Risk Ref", "Risk ID", "Related Risk"],
        "extensions": ["Extensions", "No. of Extensions", "Times Extended", "Extension Count"],
        "closed": ["Date Closed", "Closed", "Closure Date", "Completed Date", "Date Completed"],
    }, numeric=["extensions"], dates=["raised", "due", "original_due", "last_update", "closed"],
        hints=["due", "owner", "status"], sheet_words=["action", "capa", "finding", "tracker"]),
    _spec("risks", "risk register", ["id", "title"], {
        "id": ["Risk ID", "Risk Ref", "Risk No", *_ID],
        "title": ["Risk", "Risk Title", "Risk Description", "Description", "Title"],
        "category": ["Category", "Risk Category", "Risk Type", "Type"],
        "department": _DEPT,
        "owner": ["Risk Owner", *_OWNER],
        "inherent_likelihood": ["Inherent Likelihood", "Gross Likelihood"],
        "inherent_impact": ["Inherent Impact", "Gross Impact"],
        "likelihood": ["Residual Likelihood", "Likelihood", "Probability", "L"],
        "impact": ["Residual Impact", "Impact", "Severity", "Consequence", "I"],
        "rating": ["Residual Rating", "Rating", "Risk Rating", "Residual Risk Rating", "Score Rating"],
        "rag": ["RAG", "Residual RAG", "RAG Rating"],
        "controls": ["Key Controls", "Controls", "Existing Controls", "Mitigation"],
        "control_effectiveness": ["Control Effectiveness", "Control Rating", "Controls Effective"],
        "last_review": ["Last Reviewed", "Last Review", "Date Last Reviewed", "Review Date"],
        "review_months": ["Review Frequency (months)", "Review Frequency", "Review Cycle (months)", "Review Months"],
        "next_review": ["Next Review", "Next Review Date", "Review Due"],
        "linked_actions": ["Linked Actions", "Actions", "Action Refs", "Mitigating Actions"],
        "status": _STATUS,
    }, numeric=["inherent_likelihood", "inherent_impact", "likelihood", "impact", "review_months"],
        dates=["last_review", "next_review"], hints=["likelihood", "impact", "rating", "rag"],
        sheet_words=["risk"]),
    _spec("documents", "document register", ["title"], {
        "id": ["Document ID", "Doc ID", "Doc Ref", "Document Ref", "Document No", "Policy Ref", *_ID],
        "title": ["Document", "Document Title", "Title", "Policy", "Policy Name", "Procedure", "Name"],
        "doc_type": ["Document Type", "Type", "Doc Type", "Category"],
        "owner": ["Document Owner", "Policy Owner", *_OWNER],
        "department": _DEPT,
        "version": ["Version", "Issue", "Rev", "Revision", "Version No"],
        "approved": ["Approved", "Date Approved", "Approval Date", "Issue Date", "Date of Issue", "Effective Date"],
        "approver": ["Approver", "Approved By", "Approving Body", "Approving Committee"],
        "last_review": ["Last Reviewed", "Last Review", "Date Last Reviewed", "Review Date"],
        "review_months": ["Review Frequency (months)", "Review Frequency", "Review Cycle (months)", "Review Months"],
        "next_review": ["Next Review", "Next Review Date", "Review Due", "Review Due Date"],
        "status": ["Document Status", *_STATUS],
        "requirements": ["Clauses", "Clause", "Requirements", "Standard Clauses", "Regulatory References", "Mapped To"],
        "file": ["File", "File Name", "Location", "Link", "Path"],
    }, numeric=["review_months"], dates=["approved", "last_review", "next_review"],
        hints=["last_review", "next_review", "review_months", "version"],
        sheet_words=["policy", "policies", "document", "procedure", "sop"]),
    _spec("certificates", "certificate register", ["holder", "cert_type"], {
        "holder": ["Supplier", "Supplier Name", "Holder", "Organisation", "Company", "Certificate Holder", "Body"],
        "category": ["Supplier Category", "Category", "Supplier Type", "Type of Supply"],
        "cert_type": ["Certificate", "Certificate Type", "Certification", "Accreditation", "Standard", "Scheme"],
        "number": ["Certificate No", "Certificate Number", "Cert No", "Number", "Registration No"],
        "issuer": ["Issuer", "Issued By", "Certification Body", "Awarding Body", "Portal"],
        "issued": ["Issue Date", "Issued", "Date Issued", "Valid From", "Start Date"],
        "expiry": ["Expiry Date", "Expiry", "Expires", "Valid To", "Valid Until", "Renewal Date", "End Date"],
        "owner": ["Internal Owner", "Account Manager", *_OWNER],
        "contact": ["Contact", "Contact Name", "Supplier Contact"],
        "email": ["Email", "Contact Email", "Supplier Email"],
        "scope": ["Scope", "Scope of Certification", "Products"],
        "status": _STATUS,
        "file": ["File", "File Name", "Certificate File", "Location"],
    }, dates=["issued", "expiry"], hints=["expiry"], sheet_words=["certificate", "accreditation", "portal"]),
    _spec("training", "training matrix", ["person", "course"], {
        "person": ["Employee", "Name", "Staff Member", "Person", "Learner", "Employee Name"],
        "department": _DEPT,
        "role": ["Role", "Job Title", "Position"],
        "course": ["Course", "Training", "Course Name", "Module", "Qualification"],
        "completed": ["Completed", "Date Completed", "Completion Date", "Last Completed", "Date Passed"],
        "expiry": ["Expiry", "Expiry Date", "Expires", "Refresher Due", "Renewal Due", "Valid Until"],
        "refresher_months": ["Refresher (months)", "Refresher Frequency", "Validity (months)", "Renewal Months"],
        "status": _STATUS,
        "manager": ["Manager", "Line Manager"],
    }, numeric=["refresher_months"], dates=["completed", "expiry"], hints=["completed", "expiry"],
        sheet_words=["training", "lms", "skills", "competenc"]),
    _spec("audits", "audit programme", ["area"], {
        "id": ["Audit ID", "Audit Ref", *_ID],
        "area": ["Process", "Audit Area", "Area", "Process / Area", "Department Audited", "Scope"],
        "standard": ["Standard", "Management System", "Standards"],
        "requirements": ["Clauses", "Clause", "Requirements"],
        "owner": ["Process Owner", "Auditee", *_OWNER],
        "department": _DEPT,
        "auditor": ["Auditor", "Lead Auditor", "Assigned Auditor"],
        "auditor_department": ["Auditor Department", "Auditor Dept", "Auditor Team"],
        "last_audit": ["Last Audit", "Last Audited", "Date Last Audited", "Previous Audit"],
        "frequency_months": ["Frequency (months)", "Audit Frequency", "Frequency", "Interval (months)"],
        "planned": ["Planned Date", "Next Audit", "Scheduled", "Planned", "Next Planned"],
        "risk": ["Risk", "Risk Level", "Priority"],
        "status": _STATUS,
    }, numeric=["frequency_months"], dates=["last_audit", "planned"], hints=["last_audit", "frequency_months", "auditor"],
        sheet_words=["audit"]),
    _spec("incidents", "incident log", ["id", "date"], {
        "id": ["Incident ID", "Incident Ref", "Breach Ref", "Breach ID", "Report No", *_ID],
        "date": ["Date", "Incident Date", "Date of Incident", "Date Occurred", "Occurred"],
        "aware": ["Date Identified", "Identified", "Date Aware", "Discovered", "Date Discovered"],
        "reported": ["Date Reported", "Reported", "Logged", "Date Logged"],
        "type": ["Type", "Incident Type", "Category", "Breach Type", "Event Type"],
        "title": ["Title", "Summary", "Description", "Incident Description", "What Happened"],
        "department": _DEPT,
        "location": ["Location", "Site", "Where"],
        "owner": ["Investigator", "Investigation Owner", *_OWNER],
        "severity": ["Severity", "Impact", "Rating", "Injury Severity"],
        "days_lost": ["Days Lost", "Days Off", "Days Absent", "Lost Time (days)"],
        "riddor": ["RIDDOR", "RIDDOR Reported", "Reportable"],
        "regulator_decision": ["ICO Decision", "Regulator Decision", "Notifiable Decision", "Reportable Decision",
                               "FCA Notification", "Notification Decision"],
        "investigation_due": ["Investigation Due", "Investigation Due Date", "Due Date", "Target Date"],
        "status": _STATUS,
        "closed": ["Date Closed", "Closed", "Closure Date"],
        "actions": ["Actions", "Linked Actions", "Action Refs"],
    }, numeric=["days_lost"], dates=["date", "aware", "reported", "investigation_due", "closed"],
        hints=["type", "severity", "investigation_due", "days_lost"],
        sheet_words=["incident", "breach", "accident", "near miss", "complaint log", "log"]),
    _spec("people", "staff directory", ["name"], {
        "name": ["Name", "Employee", "Full Name", "Staff Member", "Person"],
        "email": ["Email", "Email Address", "Work Email"],
        "department": _DEPT,
        "role": ["Role", "Job Title", "Position"],
        "manager": ["Manager", "Line Manager", "Reports To"],
        "manager_email": ["Manager Email", "Line Manager Email"],
    }, hints=["email"], sheet_words=["people", "staff", "directory", "contacts", "owners"]),
    _spec("form_updates", "update form responses", ["reference"], {
        "submission_id": ["Submission ID", "Response ID", "Response No"],
        "submitted": ["Submitted", "Timestamp", "Completion Time", "Submitted At", "Date Submitted", "Start Time"],
        "name": ["Submitted By", "Your Name", "Name", "Respondent"],
        "email": ["Email", "Your Email", "Respondent Email"],
        "department": ["Your Department", *_DEPT],
        "reference": ["Action / Risk Ref", "Action Ref", "Reference", "Ref", "Item Ref", "Action ID", "Risk ID"],
        "update_type": ["Update Type", "Type of Update", "What Are You Updating"],
        "status": ["New Status", "Status", "Current Status"],
        "comment": ["Update", "Comment", "Comments", "Progress Update", "Details"],
        "evidence": ["Evidence", "Evidence File", "Evidence Link", "Attachment", "Evidence (file name or link)"],
        "new_due": ["Requested New Due Date", "New Due Date", "Requested Date", "Revised Date Requested"],
    }, dates=["submitted", "new_due"], hints=["submitted", "update_type", "comment"],
        sheet_words=["form", "responses", "updates"]),
    _spec("framework", "requirements framework", ["id", "title"], {
        "id": ["Clause", "Clause No", "Requirement ID", "Requirement", "Control", "Ref", "ID"],
        "title": ["Title", "Clause Title", "Requirement Title", "Description", "Name"],
        "standard": ["Standard", "Framework", "Regulation", "Source"],
        "area": ["Area", "Section", "Theme", "Category"],
        "evidence_expected": ["Evidence Expected", "Typical Evidence", "Expected Evidence", "Evidence"],
        "mandatory": ["Mandatory", "Required", "Documented Information Required"],
    }, hints=["standard", "evidence_expected"], sheet_words=["framework", "clause", "requirement"]),
    _spec("mi_history", "previous MI", ["period", "metric", "value"], {
        "period": ["Period", "Month", "Reporting Period"],
        "metric": ["Metric", "Measure", "KPI", "Indicator"],
        "value": ["Value", "Result", "Figure"],
    }, numeric=["value"], hints=["metric"], sheet_words=["mi", "history", "trend"]),
    _spec("content_requests", "content requests", ["id", "kind"], {
        "id": ["Request ID", "Request Ref", *_ID],
        "kind": ["Content Type", "Type", "Kind", "Format"],
        "title": ["Title", "Topic", "Subject", "Task"],
        "audience": ["Audience", "For", "Target Audience", "Who For"],
        "brief": ["Brief", "Key Points", "Notes", "Details", "Background"],
        "source_file": ["Source File", "Notes File", "Attachment", "Source"],
        "location": ["Location", "Site", "Area"],
        "requested_by": ["Requested By", "Requester", "Owner"],
        "due": ["Due", "Due Date", "Needed By"],
        "reviewer": ["Reviewer", "Approver", "Competent Person", "Review By"],
    }, dates=["due"], hints=["kind", "audience", "brief"], sheet_words=["content", "request", "comms"]),
    _spec("hazards", "risk assessment hazards", ["request_id", "hazard"], {
        "request_id": ["Request ID", "Assessment ID", "RA Ref", "Risk Assessment", "Request Ref"],
        "hazard": ["Hazard", "Hazard Description", "Hazards"],
        "who": ["Who Might Be Harmed", "Who", "Persons at Risk", "At Risk"],
        "controls": ["Existing Controls", "Current Controls", "Controls in Place", "Controls"],
        "likelihood": ["Likelihood", "L", "Probability"],
        "severity": ["Severity", "S", "Consequence", "Impact"],
        "further_controls": ["Further Controls", "Additional Controls", "Further Action", "Actions Required"],
        "residual_likelihood": ["Residual Likelihood", "Residual L"],
        "residual_severity": ["Residual Severity", "Residual S"],
        "action_owner": ["Action Owner", "Owner", "By Whom"],
    }, numeric=["likelihood", "severity", "residual_likelihood", "residual_severity"],
        hints=["likelihood", "severity", "controls"], sheet_words=["hazard"]),
    _spec("sales", "sales export", ["date"], {
        "date": ["Date", "Order Date", "Invoice Date", "Sale Date", "Trading Date", "Day"],
        "order_id": ["Order ID", "Order No", "Order Number", "Invoice No", "Transaction ID", "Reference"],
        "customer": ["Customer", "Customer Name", "Account", "Account Name"],
        "channel": ["Channel", "Sales Channel", "Route to Market"],
        "product": ["Product", "SKU", "Item", "Product Name", "Product Code"],
        "site": ["Site", "Branch", "Location", "Depot"],
        "quantity": ["Qty", "Quantity", "Units", "Cases"],
        "net_sales": ["Net Sales", "Net Value", "Net Amount", "Sales (£)", "Value", "Net", "Revenue"],
        "cost": ["Cost", "Cost of Sales", "COGS"],
    }, numeric=["quantity", "net_sales", "cost"], dates=["date"], hints=["net_sales", "quantity", "order_id"],
        sheet_words=["sales", "orders"]),
]}

# Upload routing: the first role whose required + hint columns are present wins,
# so the more specific shapes come first.
DETECT_ORDER = ["form_updates", "hazards", "content_requests", "mi_history", "framework", "certificates", "training",
                "audits", "incidents", "risks", "actions", "documents", "sales", "people"]


def norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def table_spec(role: str, config: dict | None = None) -> TableSpec:
    """Default spec for a role, plus any aliases / label / extra columns from ``config['tables'][role]``."""
    base = TABLE_SPECS[role]
    extra = ((config or {}).get("tables") or {}).get(role) or {}
    aliases = {k: list(v) for k, v in base.aliases.items()}
    for col, names in (extra.get("aliases") or {}).items():
        aliases[col] = list(names) + aliases.get(col, [])
    numeric = base.numeric + [c for c in extra.get("numeric", []) if c not in base.numeric]
    dates = base.dates + [c for c in extra.get("dates", []) if c not in base.dates]
    return TableSpec(role, extra.get("label", base.label), list(extra.get("required", base.required)), aliases,
                     numeric, dates, list(extra.get("hints", base.hints)), base.sheet_words)


@dataclass
class LoadedTable:
    role: str
    name: str  # file name
    sheet: str | None
    df: pd.DataFrame  # canonical columns + any extra columns under their own headings
    headings: dict[str, str]  # canonical -> heading as it appears in the file
    order: list[str]  # column order in the file (canonical names for mapped columns)
    bad_cells: list[str] = field(default_factory=list)

    @property
    def where(self) -> str:
        return str(self.df["_source"].iloc[0]) if len(self.df) else self.name


def read_sheets(name: str, data: bytes) -> list[tuple[str | None, pd.DataFrame]]:
    """Every non-empty sheet of a workbook (or the one table in a CSV) as raw text frames."""
    suffix = Path(name).suffix.lower()
    if not data:
        raise DataFileError(f"“{name}” is empty.")
    try:
        if suffix in (".csv", ".txt"):
            frames = [(None, _read_csv(data))]
        elif suffix in (".xlsx", ".xlsm", ".xls"):
            book = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object)
            frames = list(book.items())
        else:
            raise DataFileError(f"“{name}” is a {suffix or 'file'} file. Please upload CSV or Excel (.xlsx) tables.")
    except DataFileError:
        raise
    except Exception as exc:  # pandas / openpyxl raise many types
        raise DataFileError(f"“{name}” could not be read as a {suffix.lstrip('.').upper()} table "
                            f"({type(exc).__name__}).") from exc
    out = []
    for sheet, df in frames:
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df.columns = [str(c).strip() for c in df.columns]
        df = df[[c for c in df.columns if not c.lower().startswith("unnamed")]]
        if not df.empty and len(df.columns) >= 2:
            out.append((sheet, df.reset_index(drop=True)))
    if not out:
        raise DataFileError(f"“{name}” has no data rows.")
    return out


def _read_csv(data: bytes) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, skipinitialspace=True)


def _mapping(columns: list[str], spec: TableSpec) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, names in spec.aliases.items():
        for alias in [canonical, *names]:
            lookup.setdefault(norm(alias), canonical)
    mapped, seen = {}, set()
    for col in columns:
        canonical = lookup.get(norm(col))
        if canonical and canonical not in seen:
            mapped[col] = canonical
            seen.add(canonical)
    return mapped


def load_frame(df: pd.DataFrame, spec: TableSpec, name: str, sheet: str | None = None,
               show_sheet: bool = True) -> LoadedTable:
    """Map one raw frame to canonical columns; raise DataFileError if required columns are missing.
    ``show_sheet`` names the sheet in messages and the source column (off for a one-sheet workbook)."""
    mapped = _mapping(list(df.columns), spec)
    missing = [c for c in spec.required if c not in mapped.values()]
    where = f"“{name}”" + (f" (sheet “{sheet}”)" if sheet and show_sheet else "")
    if missing:
        wanted = "; ".join(f"{c.replace('_', ' ')} (e.g. {', '.join(spec.aliases.get(c, [c])[:3])})" for c in missing)
        raise DataFileError(f"{where} doesn't look like a {spec.label}: missing column(s) {wanted}. "
                            f"Found: {', '.join(df.columns)}.")
    out = df.rename(columns=mapped).reset_index(drop=True)
    bad: list[str] = []
    for col in spec.numeric:
        if col in out:
            before = out[col].copy()
            out[col], mask = coerce_numeric(out[col].map(lambda v: v if not isinstance(v, str) else v.strip()))
            bad += [f"row {i + 2} {col.replace('_', ' ')} “{before[i]}”" for i in out.index[mask]]
    for col in spec.dates:
        if col in out:
            before = out[col].copy()
            out[col], mask = coerce_dates(out[col].map(_date_text))
            bad += [f"row {i + 2} {col.replace('_', ' ')} “{before[i]}”" for i in out.index[mask]]
    typed = set(spec.numeric) | set(spec.dates)
    for col in out.columns:
        if col not in typed:
            out[col] = pd.Series([text(v) for v in out[col]], index=out.index, dtype=object)
    for col in spec.aliases:  # every canonical column exists, so checks never need "if col in df"
        if col not in out:
            out[col] = pd.NaT if col in spec.dates else (float("nan") if col in spec.numeric else "")
    out["_source"] = f"{name} › {sheet}" if sheet and show_sheet else name
    out["_row"] = out.index + 2
    headings = {v: k for k, v in mapped.items()}
    order = [mapped.get(c, c) for c in df.columns]
    return LoadedTable(spec.role, name, sheet, out, headings, order, bad)


def _date_text(v):
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    return v


def text(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def load_table(name: str, data: bytes, spec: TableSpec, sheet: str | None = None) -> LoadedTable:
    """Read one table. ``sheet`` picks a sheet of a workbook (default: the first one that fits the role)."""
    sheets = read_sheets(name, data)
    if sheet is not None:
        chosen = [(s, df) for s, df in sheets if s == sheet]
        if not chosen:
            raise DataFileError(f"“{name}” has no sheet called “{sheet}”. Sheets: {', '.join(str(s) for s, _ in sheets)}.")
        return load_frame(chosen[0][1], spec, name, sheet, len(sheets) > 1)
    errors = []
    for s, df in sheets:
        try:
            return load_frame(df, spec, name, s, len(sheets) > 1)
        except DataFileError as exc:
            errors.append(str(exc))
    raise DataFileError(errors[0])


def detect_role(columns: list[str], sheet_or_file: str, config: dict | None = None,
                allowed: list[str] | None = None) -> str | None:
    """Work out what a table is from its headings (and, as a tie-break, its sheet or file name)."""
    words = sheet_or_file.lower()
    candidates = []
    for role in DETECT_ORDER:
        if allowed is not None and role not in allowed:
            continue
        spec = table_spec(role, config)
        mapped = set(_mapping(columns, spec).values())
        if not set(spec.required) <= mapped:
            continue
        if spec.hints and not (set(spec.hints) & mapped):
            continue
        named = any(w in words for w in spec.sheet_words)
        candidates.append((0 if named else 1, DETECT_ORDER.index(role), role))
    return min(candidates)[2] if candidates else None


def route_upload(name: str, data: bytes, config: dict | None = None,
                 allowed: list[str] | None = None) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Which role each sheet of an uploaded table is. Returns ([(role, sheet)], notes for unrecognised sheets)."""
    routed, notes = [], []
    try:
        sheets = read_sheets(name, data)
    except DataFileError as exc:
        return [], [str(exc)]
    for sheet, df in sheets:
        role = detect_role(list(df.columns), f"{sheet or ''} {Path(name).stem}", config, allowed)
        label = f"“{name}”" + (f" sheet “{sheet}”" if sheet else "")
        if role is None:
            notes.append(f"{label}: could not tell what this table is from its column headings, so it was skipped.")
        else:
            routed.append((role, sheet if len(sheets) > 1 else None))
    return routed, notes

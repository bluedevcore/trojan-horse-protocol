"""Findings (exceptions) raised by the compliance checks.

Every check has defaults in ``CHECKS``. A client config overrides any of them
under ``checks.<check_id>`` (``label``, ``severity``, ``needs_human_check``,
``letter``, ``enabled``, ``action``, ``area``).

``letter: owner`` means the finding becomes a point in a drafted email to the
item's owner (findings for the same owner share one email). ``letter:
holder`` sends it to the certificate holder (e.g. a supplier). ``letter:
<contact key>`` sends it to a fixed person under ``contacts`` in the config.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
AREA_ORDER = ["Updates", "Mailbox", "Actions", "Risks", "Incidents", "Documents", "Evidence", "Certificates",
              "Training", "Audits", "KPIs", "Content"]


def _c(label, area, severity, human, action, letter=""):
    return dict(label=label, area=area, severity=severity, human=human, action=action, letter=letter)


# check id: label, area, severity, needs a human check, suggested action, letter recipient
CHECKS: dict[str, dict] = {
    # department updates (emails and form responses)
    "update_extension_request": _c("Extension requested", "Updates", "Medium", True,
                                   "Approve or refuse the new date; the register keeps the current date until then."),
    "update_inferred_reference": _c("Update matched by AI, not by reference", "Updates", "Medium", True,
                                    "Confirm which register item this update is about before it is applied."),
    "update_unknown_reference": _c("Reference not in the register", "Updates", "Medium", True,
                                   "Check the reference with the sender; nothing was changed."),
    "update_ambiguous_reference": _c("Reference matches more than one item", "Updates", "Medium", True,
                                     "Fix the duplicate reference, then apply the update by hand."),
    "update_no_evidence": _c("Completion reported without evidence", "Updates", "Medium", False,
                             "Evidence requested in the drafted email; the item stays open until it arrives.", "owner"),
    "update_not_owner": _c("Update not from the owner", "Updates", "Low", True,
                           "Confirm the update with the owner; it was not applied."),
    "update_duplicate": _c("Duplicate form response", "Updates", "Low", False,
                           "Counted once. No action needed."),
    "update_item_closed": _c("Update for a closed item", "Updates", "Low", True,
                             "Check whether the item should be reopened."),
    "update_new_entry": _c("New register entry proposed", "Updates", "High", True,
                           "Check the proposed entry, then add it to the register."),
    "update_unclear": _c("Update needs reading by a person", "Updates", "Low", True,
                         "Read the message and update the register by hand if needed."),
    # mailbox triage
    "message_routed": _c("Message needs routing", "Mailbox", "Medium", True,
                         "Forward to the team shown and log it; note the deadline."),
    "message_deadline": _c("Deadline from the mailbox", "Mailbox", "High", True,
                           "Make sure the named person has it in hand before the deadline."),
    "message_unclassified": _c("Message not classified", "Mailbox", "Low", True,
                               "Read the message and route it by hand."),
    # actions
    "action_overdue": _c("Action overdue", "Actions", "Medium", False,
                         "Chased in the drafted email to the owner.", "owner"),
    "action_no_owner": _c("Action has no owner", "Actions", "Medium", True,
                          "Agree an owner with the department head and record it."),
    "action_no_due_date": _c("Action has no due date", "Actions", "Low", True,
                             "Agree a due date with the owner and record it."),
    "action_closed_no_evidence": _c("Closed without evidence", "Actions", "Medium", False,
                                    "Evidence requested in the drafted email; reopen the action if none is held.", "owner"),
    "action_stale": _c("No update for a long time", "Actions", "Low", False,
                       "Update requested in the drafted email.", "owner"),
    "action_extended": _c("Repeatedly extended", "Actions", "Medium", True,
                          "Escalate to the committee: agree a final date or accept the risk."),
    "action_dates_invalid": _c("Dates don't make sense", "Actions", "Low", True,
                               "Correct the dates in the register."),
    "duplicate_id": _c("Duplicate reference", "Actions", "Medium", True,
                       "Give one of the entries a new reference so updates can't go to the wrong one."),
    # risks
    "risk_review_overdue": _c("Risk review overdue", "Risks", "Medium", False,
                              "Review requested in the drafted email to the risk owner.", "owner"),
    "risk_rating_mismatch": _c("Rating doesn't match the scores", "Risks", "High", True,
                               "Agree the scores and the rating with the risk owner and correct the register."),
    "risk_red_no_action": _c("High risk with no open action", "Risks", "Medium", True,
                             "Agree a mitigating action, or record that the risk is accepted."),
    "risk_no_owner": _c("Risk has no owner", "Risks", "Medium", True, "Assign a risk owner."),
    "risk_scores_missing": _c("Risk scores missing", "Risks", "Low", True, "Score the risk."),
    # incidents / breaches / accidents
    "incident_investigation_overdue": _c("Investigation overdue", "Incidents", "Medium", False,
                                         "Update requested in the drafted email to the investigator.", "owner"),
    "incident_decision_missing": _c("Reporting decision not recorded", "Incidents", "High", True,
                                    "Record whether it was reported (and why), or assess it now."),
    "incident_possibly_reportable": _c("May need reporting to a regulator", "Incidents", "High", True,
                                       "A competent person should decide whether it is reportable and record it."),
    "incident_no_investigator": _c("No investigator assigned", "Incidents", "Medium", True, "Assign an investigator."),
    # controlled documents and policies
    "document_review_overdue": _c("Review overdue", "Documents", "Medium", False,
                                  "Review requested in the drafted email to the owner.", "owner"),
    "document_not_approved": _c("Not approved", "Documents", "Medium", True,
                                "Take it to the approver; the previous approved version still applies."),
    "document_no_owner": _c("Document has no owner", "Documents", "Low", True, "Assign an owner."),
    "document_no_review_date": _c("No review date", "Documents", "Low", True, "Set a review date."),
    # documents read with Claude (evidence)
    "document_unreadable": _c("Document could not be read", "Evidence", "Medium", True,
                              "Open the file and check it by hand, or upload a text-based copy."),
    "document_low_confidence": _c("Document hard to read", "Evidence", "Low", True,
                                  "Compare what was read with the document."),
    "evidence_out_of_date": _c("Evidence out of date", "Evidence", "Medium", False,
                               "Ask the owner for the current version.", "owner"),
    "requirement_gap": _c("No evidence for a requirement", "Evidence", "High", True,
                          "Find or create evidence before the audit, or record why it does not apply."),
    "requirement_partial": _c("Evidence is only partial", "Evidence", "Low", True,
                              "Check whether the evidence is enough for the auditor."),
    "requirement_out_of_date": _c("Only out-of-date evidence", "Evidence", "Medium", True,
                                  "Get the current version before the audit."),
    # certificates and accreditations
    "certificate_expired": _c("Certificate expired", "Certificates", "High", True,
                              "Ask for the renewed certificate; check whether supply or work can continue.", "holder"),
    "certificate_expiring": _c("Certificate expiring soon", "Certificates", "Medium", False,
                               "Renewal reminder drafted.", "holder"),
    "certificate_missing": _c("Required certificate not on file", "Certificates", "High", True,
                              "Ask for the certificate; check whether supply or work can continue.", "holder"),
    "certificate_no_expiry": _c("No expiry date recorded", "Certificates", "Low", True,
                                "Check the certificate and record its expiry date."),
    # training
    "training_expired": _c("Training expired", "Training", "Medium", False,
                           "Refresher requested in the drafted email.", "owner"),
    "training_expiring": _c("Training due soon", "Training", "Low", False, "Reminder drafted.", "owner"),
    "training_missing": _c("Required training not recorded", "Training", "Medium", True,
                           "Book the course, or record the completion if it was done."),
    # audit programme
    "audit_overdue": _c("Audit overdue", "Audits", "Medium", True, "Schedule the audit and agree a date."),
    "audit_not_scheduled": _c("Audit not scheduled", "Audits", "Low", True, "Add a planned date to the programme."),
    "auditor_not_independent": _c("Auditor not independent", "Audits", "Medium", True,
                                  "Assign an auditor from another area."),
    # KPI report
    "kpi_missing_day": _c("No sales on a trading day", "KPIs", "Medium", True,
                          "Check the export for the missing day before the report is sent."),
    "kpi_negative": _c("Negative sales line", "KPIs", "Low", True, "Check it is a genuine credit or return."),
    "kpi_duplicate": _c("Duplicate sales line", "KPIs", "Medium", True,
                        "Counted once; check whether the order was entered twice."),
    "kpi_outlier": _c("Unusual sales line", "KPIs", "Low", True, "Check the line for a keying error."),
    "kpi_below_target": _c("Below target", "KPIs", "Low", False, "Shown in the KPI report."),
    # drafted content
    "content_high_residual": _c("Risk still high after controls", "Content", "High", True,
                                "A competent person must agree further controls before work goes ahead."),
    "content_missing_input": _c("Draft request incomplete", "Content", "Low", True,
                                "Add the missing detail to the request and re-run."),
}


@dataclass
class Finding:
    check_id: str
    ref: str  # register item id (A-108, R-05, POL-07, file name...)
    subject: str  # short description of the item
    finding: str  # deterministic plain-English description
    owner: str = ""  # who the item belongs to (letter recipient for letter: owner)
    department: str = ""
    date: pd.Timestamp | None = None
    days: int | None = None  # days overdue / to deadline (drives chase tiers)
    source: str = ""
    point: str = ""  # one line for the drafted email
    action: str = ""  # overrides the default suggested action
    severity: str = ""  # overrides the default severity
    human: bool | None = None  # overrides the default needs-human-check
    # filled from CHECKS + config
    label: str = ""
    area: str = ""
    needs_human_check: bool = False
    letter: str = ""
    id: str = ""


def configure(f: Finding, config: dict) -> Finding | None:
    """Apply registry defaults and client overrides; None if the check is switched off."""
    base = dict(CHECKS.get(f.check_id, {}))
    base.update((config.get("checks") or {}).get(f.check_id) or {})
    if base.get("enabled") is False:
        return None
    f.label = base.get("label", f.check_id)
    f.area = base.get("area", "Actions")
    f.severity = f.severity or str(base.get("severity", "Medium")).capitalize()
    default_human = bool(base.get("needs_human_check", base.get("human", False)))
    f.needs_human_check = default_human if f.human is None or "needs_human_check" in (
        (config.get("checks") or {}).get(f.check_id) or {}) else bool(f.human)
    f.letter = base.get("letter", "") or ""
    f.action = f.action or base.get("action", "")
    return f


def finalise(findings: list[Finding], config: dict) -> list[Finding]:
    """Configure, sort (area, severity, date, ref) and number EX-01, EX-02, ..."""
    out = [f for f in (configure(x, config) for x in findings) if f is not None]
    order = list((config.get("views") or {}).get("area_order") or AREA_ORDER)
    rank = {a: i for i, a in enumerate(order)}
    out.sort(key=lambda f: (rank.get(f.area, 99), SEVERITY_ORDER.get(f.severity, 3),
                            f.date if f.date is not None else pd.Timestamp.max, f.ref))
    for i, f in enumerate(out, 1):
        f.id = f"EX-{i:02d}"
    return out


def findings_frame(findings: list[Finding]) -> pd.DataFrame:
    cols = ["ID", "Severity", "Area", "Check", "Ref", "Item", "Owner", "Department", "Date", "Finding",
            "Suggested action", "Needs human check", "Email to", "Source"]
    rows = [{
        "ID": f.id, "Severity": f.severity, "Area": f.area, "Check": f.label, "Ref": f.ref, "Item": f.subject,
        "Owner": f.owner, "Department": f.department, "Date": f.date, "Finding": f.finding,
        "Suggested action": f.action, "Needs human check": "Yes" if f.needs_human_check else "No",
        "Email to": f.owner if f.letter else "", "Source": f.source,
    } for f in findings]
    return pd.DataFrame(rows, columns=cols)

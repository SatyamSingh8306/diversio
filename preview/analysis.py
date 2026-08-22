"""HRIS CSV parsing and hierarchy analysis.

This module is deliberately framework-free: it works on plain dataclasses so
it can be unit-tested without driving a browser or Django's test client. The
Django view is a thin layer that calls into :func:`analyze`.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

EXPECTED_HEADERS = [
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
]


class HrisError(Exception):
    """Raised for malformed uploads (bad encoding, missing headers, etc.)."""


@dataclass
class Employee:
    """A single normalized source row, after identity validation.

    ``manager`` is the resolved manager Employee (or None). ``manager_error``
    is set when the manager reference could not be resolved; in that case the
    employee stays accepted but produces no reporting relationship and is not
    a root.
    """

    source_row: int
    employee_id: str
    employee_name: str
    email: str
    manager_id: str
    manager_email: str
    department: str
    identity_valid: bool = True
    identity_errors: list = field(default_factory=list)
    manager: Optional["Employee"] = None
    manager_error: Optional[str] = None


@dataclass
class ValidationError:
    source_row: int
    message: str


@dataclass
class ManagerInfo:
    employee: Employee
    direct_report_count: int


@dataclass
class AnalysisResult:
    total_rows: int
    accepted_employees: list
    validation_errors: list
    root_employees: list
    managers: list
    cyclic_employees: list


def _normalize_row(raw: dict) -> dict:
    """Trim every value; lowercase email and manager_email; keep IDs case-sensitive."""
    return {
        "employee_id": (raw.get("employee_id") or "").strip(),
        "employee_name": (raw.get("employee_name") or "").strip(),
        "email": (raw.get("email") or "").strip().lower(),
        "manager_id": (raw.get("manager_id") or "").strip(),
        "manager_email": (raw.get("manager_email") or "").strip().lower(),
        "department": (raw.get("department") or "").strip(),
    }


def parse_csv(file_content: bytes):
    """Decode and parse raw CSV bytes into ``(line_no, normalized_dict)`` tuples.

    ``line_no`` is the 1-based source row in the original file, with the header
    counted as row 1 (so the first data row is row 2). UTF-8 with or without a
    BOM is supported.
    """
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HrisError(f"File is not valid UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HrisError("CSV appears to be empty or has no header row.")

    missing = [h for h in EXPECTED_HEADERS if h not in reader.fieldnames]
    if missing:
        raise HrisError(
            "CSV is missing required header(s): " + ", ".join(missing)
        )

    rows = []
    for line_no, raw in enumerate(reader, start=2):
        rows.append((line_no, _normalize_row(raw)))
    return rows


def validate_identity(rows):
    """Return Employee objects with identity validity marked.

    A row is identity-invalid when ``employee_id`` or ``email`` is blank, or
    when either value is duplicated anywhere in the file. Every row that
    shares a duplicated value is invalid (including the first occurrence),
    because there is no way to tell which row is canonical.
    """
    id_rows: dict = {}
    email_rows: dict = {}
    for line_no, norm in rows:
        id_rows.setdefault(norm["employee_id"], []).append(line_no)
        email_rows.setdefault(norm["email"], []).append(line_no)

    employees = []
    for line_no, norm in rows:
        errors = []
        eid = norm["employee_id"]
        email = norm["email"]

        if not eid:
            errors.append("employee_id is required but was blank.")
        else:
            others = [r for r in id_rows[eid] if r != line_no]
            if others:
                errors.append(
                    f"employee_id '{eid}' is duplicated on source row(s): "
                    + ", ".join(str(r) for r in others)
                    + "."
                )

        if not email:
            errors.append("email is required but was blank.")
        else:
            others = [r for r in email_rows[email] if r != line_no]
            if others:
                errors.append(
                    f"email '{email}' is duplicated on source row(s): "
                    + ", ".join(str(r) for r in others)
                    + "."
                )

        employees.append(
            Employee(
                source_row=line_no,
                employee_id=eid,
                employee_name=norm["employee_name"],
                email=email,
                manager_id=norm["manager_id"],
                manager_email=norm["manager_email"],
                department=norm["department"],
                identity_valid=not errors,
                identity_errors=errors,
            )
        )
    return employees


def resolve_managers(employees):
    """Resolve each accepted employee's manager reference.

    Managers are looked up only among identity-valid employees. Rules:

    * both manager fields blank  -> root (no manager, no error)
    * only manager_id           -> lookup by employee_id (case-sensitive)
    * only manager_email         -> lookup by normalized email
    * both supplied             -> both must resolve to the same employee
    * self-management           -> error

    A manager error leaves the employee accepted but with ``manager = None``.
    """
    by_id = {e.employee_id: e for e in employees if e.identity_valid}
    by_email = {e.email: e for e in employees if e.identity_valid}

    for e in employees:
        if not e.identity_valid:
            continue

        mid = e.manager_id
        memail = e.manager_email

        if not mid and not memail:
            e.manager = None
            continue

        if mid and memail:
            ref_id = by_id.get(mid)
            ref_email = by_email.get(memail)
            if ref_id is None and ref_email is None:
                e.manager_error = (
                    f"manager not found: manager_id '{mid}' and manager_email "
                    f"'{memail}' do not match any employee."
                )
            elif ref_id is None:
                e.manager_error = (
                    f"manager not found: manager_id '{mid}' does not match any employee."
                )
            elif ref_email is None:
                e.manager_error = (
                    f"manager not found: manager_email '{memail}' does not match any employee."
                )
            elif ref_id is ref_email:
                e.manager = ref_id
            else:
                e.manager_error = (
                    f"manager conflict: manager_id '{mid}' identifies "
                    f"{ref_id.employee_id} but manager_email '{memail}' identifies "
                    f"{ref_email.employee_id}."
                )
        elif mid:
            ref = by_id.get(mid)
            if ref is None:
                e.manager_error = (
                    f"manager not found: manager_id '{mid}' does not match any employee."
                )
            else:
                e.manager = ref
        else:  # memail only
            ref = by_email.get(memail)
            if ref is None:
                e.manager_error = (
                    f"manager not found: manager_email '{memail}' does not match any employee."
                )
            else:
                e.manager = ref

        if e.manager is e:
            e.manager_error = (
                f"employee manages themselves (manager reference resolves to self)."
            )
            e.manager = None


def find_cyclic_employees(employees):
    """Return the set of employee_ids that are members of a reporting cycle.

    The reporting graph is a functional graph: each employee has at most one
    outgoing edge (their manager). We walk each unvisited chain, recording
    nodes as "in progress". Hitting an in-progress node means we closed a loop;
    every node from that point to the end of the chain is a cycle member. Nodes
    that merely report *into* a cycle are not marked.

    Time O(V + E), space O(V). With out-degree <= 1 this is O(N).
    """
    state = {}  # employee_id -> 0 unvisited, 1 in-progress, 2 done
    cyclic = set()

    for start in employees:
        if state.get(start.employee_id, 0) == 2:
            continue
        chain = []
        cur = start
        while cur is not None and state.get(cur.employee_id, 0) == 0:
            state[cur.employee_id] = 1
            chain.append(cur)
            cur = cur.manager
        if cur is not None and state.get(cur.employee_id, 0) == 1:
            in_cycle = False
            for node in chain:
                if node is cur:
                    in_cycle = True
                if in_cycle:
                    cyclic.add(node.employee_id)
        for node in chain:
            state[node.employee_id] = 2

    return cyclic


def analyze(file_content: bytes) -> AnalysisResult:
    """Run the full parse -> validate -> resolve -> analyze pipeline."""
    rows = parse_csv(file_content)
    if not rows:
        raise HrisError("CSV contains a header row but no data rows.")

    employees = validate_identity(rows)
    resolve_managers(employees)

    accepted = [e for e in employees if e.identity_valid]

    validation_errors = []
    for e in employees:
        for err in e.identity_errors:
            validation_errors.append(ValidationError(source_row=e.source_row, message=err))
        if e.manager_error:
            validation_errors.append(
                ValidationError(source_row=e.source_row, message=e.manager_error)
            )

    roots = [
        e for e in accepted
        if not e.manager_id and not e.manager_email and not e.manager_error
    ]
    roots.sort(key=lambda e: e.employee_id)

    report_counts: dict = {}
    for e in accepted:
        if e.manager is not None:
            report_counts[e.manager.employee_id] = (
                report_counts.get(e.manager.employee_id, 0) + 1
            )

    managers = [
        ManagerInfo(employee=e, direct_report_count=report_counts[e.employee_id])
        for e in accepted
        if report_counts.get(e.employee_id, 0) > 0
    ]
    managers.sort(key=lambda m: (-m.direct_report_count, m.employee.employee_id))

    cyclic_ids = find_cyclic_employees(accepted)
    cyclic_employees = [e for e in accepted if e.employee_id in cyclic_ids]
    cyclic_employees.sort(key=lambda e: e.employee_id)

    return AnalysisResult(
        total_rows=len(rows),
        accepted_employees=accepted,
        validation_errors=validation_errors,
        root_employees=roots,
        managers=managers,
        cyclic_employees=cyclic_employees,
    )
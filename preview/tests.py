"""Tests for the HRIS analysis logic.

These tests exercise the parsing and hierarchy logic directly, without a
browser, which is the behavior the assignment asks us to keep testable.
"""
import unittest
from dataclasses import dataclass
from typing import Optional

from preview.analysis import (
    HrisError,
    analyze,
    find_cyclic_employees,
    parse_csv,
    resolve_managers,
    validate_identity,
)


@dataclass
class _StubEmployee:
    """Tiny typed stand-in for tests that don't need the full Employee.

    Exposes only the attributes used by :func:`resolve_managers` and
    :func:`find_cyclic_employees`. Using a real class (instead of
    ``type("E", (), {...})()``) keeps Pylance and mypy happy.
    """

    employee_id: str
    email: str = ""
    manager_id: str = ""
    manager_email: str = ""
    identity_valid: bool = True
    manager: Optional["_StubEmployee"] = None
    manager_error: Optional[str] = None


SAMPLE = b"""employee_id,employee_name,email,manager_id,manager_email,department
DIV-1001,Avery Morgan,demo.avery.morgan@diversio.com,,,Executive
DIV-1200,Mateo Rivera,demo.mateo.rivera@diversio.com,,DEMO.AVERY.MORGAN@diversio.com,Product
DIV-1210,Camille Laurent,demo.camille.laurent@diversio.com,DIV-1200,,Product
DIV-1412,"Alvarez, Ren\xc3\xa9e",demo.renee.alvarez@diversio.com,DIV-1400,DEMO.LENA.OKAFOR@diversio.com,Operations
"""


def _rows_from_csv(csv_bytes):
    """Helper: parse CSV bytes into the (line_no, normalized_dict) tuples."""
    return parse_csv(csv_bytes)


class TestParsing(unittest.TestCase):
    def test_parse_csv_normalizes_and_counts_rows(self):
        rows = _rows_from_csv(SAMPLE)
        # 4 data rows; line numbers start at 2 (header is row 1)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0], 2)
        # email is lowercased
        self.assertEqual(rows[0][1]["email"], "demo.avery.morgan@diversio.com")
        # manager_email lowercased
        self.assertEqual(rows[1][1]["manager_email"], "demo.avery.morgan@diversio.com")
        # IDs stay case-sensitive
        self.assertEqual(rows[0][1]["employee_id"], "DIV-1001")

    def test_quoted_commas_are_preserved(self):
        rows = _rows_from_csv(SAMPLE)
        self.assertEqual(rows[3][1]["employee_name"], "Alvarez, Ren\u00e9e")

    def test_bom_is_stripped(self):
        rows = _rows_from_csv(b"\xef\xbb\xbf" + SAMPLE)
        self.assertEqual(len(rows), 4)

    def test_missing_header_raises(self):
        with self.assertRaises(HrisError):
            parse_csv(b"foo,bar\n1,2\n")

    def test_unknown_header_raises(self):
        with self.assertRaises(HrisError):
            parse_csv(b"employee_id,email\nDIV-1,a@b.com\n")

    def test_bad_encoding_raises(self):
        with self.assertRaises(HrisError):
            parse_csv(b"\xff\xfe not utf-8")


class TestIdentity(unittest.TestCase):
    def test_duplicate_email_makes_rows_invalid(self):
        rows = [
            (2, {"employee_id": "A", "email": "x@y.com", "employee_name": "",
                 "manager_id": "", "manager_email": "", "department": ""}),
            (3, {"employee_id": "B", "email": "x@y.com", "employee_name": "",
                 "manager_id": "", "manager_email": "", "department": ""}),
        ]
        emps = validate_identity(rows)
        self.assertFalse(emps[0].identity_valid)
        self.assertFalse(emps[1].identity_valid)

    def test_blank_id_is_invalid(self):
        rows = [
            (2, {"employee_id": "", "email": "x@y.com", "employee_name": "",
                 "manager_id": "", "manager_email": "", "department": ""}),
        ]
        emps = validate_identity(rows)
        self.assertFalse(emps[0].identity_valid)


class TestManagerResolution(unittest.TestCase):
    @staticmethod
    def _emp(eid, email, mid="", memail=""):
        # Mimic _normalize_row: emails are stored lowercased.
        return _StubEmployee(
            employee_id=eid,
            email=email.lower(),
            manager_id=mid,
            manager_email=memail.lower(),
            identity_valid=True,
        )

    def test_manager_lookup_by_email_is_case_insensitive(self):
        a = self._emp("A", "a@y.com")
        b = self._emp("B", "b@y.com", memail="A@Y.COM")
        resolve_managers([a, b])
        self.assertIs(b.manager, a)
        self.assertIsNone(b.manager_error)

    def test_both_references_must_identify_same_employee(self):
        a = self._emp("A", "a@y.com")
        b = self._emp("B", "b@y.com", mid="A", memail="c@y.com")
        resolve_managers([a, b])
        self.assertIsNotNone(b.manager_error)
        self.assertIsNone(b.manager)

    def test_self_management_is_an_error(self):
        a = self._emp("A", "a@y.com", mid="A")
        resolve_managers([a])
        self.assertIsNotNone(a.manager_error)
        self.assertIsNone(a.manager)

    def test_missing_manager_is_an_error_but_employee_stays_accepted(self):
        a = self._emp("A", "a@y.com", mid="NOPE")
        resolve_managers([a])
        self.assertIsNotNone(a.manager_error)
        self.assertIsNone(a.manager)


class TestCycles(unittest.TestCase):
    def test_simple_cycle_detected(self):
        # A -> B -> A
        a = _StubEmployee(employee_id="A")
        b = _StubEmployee(employee_id="B", manager=a)
        a.manager = b
        cyclic = find_cyclic_employees([a, b])
        self.assertEqual(cyclic, {"A", "B"})

    def test_node_reporting_into_cycle_is_not_cyclic(self):
        # C -> A -> B -> A ; only A and B are in the cycle
        a = _StubEmployee(employee_id="A")
        b = _StubEmployee(employee_id="B", manager=a)
        c = _StubEmployee(employee_id="C", manager=a)
        a.manager = b
        cyclic = find_cyclic_employees([a, b, c])
        self.assertEqual(cyclic, {"A", "B"})

    def test_acyclic_chain_has_no_cycles(self):
        # A -> B -> C (root)
        a = _StubEmployee(employee_id="A")
        b = _StubEmployee(employee_id="B")
        c = _StubEmployee(employee_id="C")
        a.manager = b
        b.manager = c
        self.assertEqual(find_cyclic_employees([a, b, c]), set())


class TestEndToEnd(unittest.TestCase):
    def test_full_analysis_on_sample(self):
        result = analyze(SAMPLE)
        self.assertEqual(result.total_rows, 4)
        self.assertEqual(len(result.accepted_employees), 4)
        # Ren\u00e9e's manager (DIV-1400 / Lena) does not exist -> 1 error
        self.assertEqual(len(result.validation_errors), 1)
        # Avery is the only root (no manager fields)
        self.assertEqual([e.employee_id for e in result.root_employees], ["DIV-1001"])
        # Mateo reports to Avery; Camille reports to Mateo -> 2 managers, 1 report each
        self.assertEqual(len(result.managers), 2)
        by_id = {m.employee.employee_id: m.direct_report_count for m in result.managers}
        self.assertEqual(by_id, {"DIV-1200": 1, "DIV-1001": 1})
        renee = [e for e in result.accepted_employees if e.employee_id == "DIV-1412"][0]
        self.assertIsNotNone(renee.manager_error)
        self.assertIsNone(renee.manager)
        self.assertEqual(len(result.cyclic_employees), 0)

    def test_cycle_in_file_is_reported(self):
        csv_bytes = (
            b"employee_id,employee_name,email,manager_id,manager_email,department\n"
            b"DIV-1,A,a@y.com,DIV-2,,\n"
            b"DIV-2,B,b@y.com,DIV-1,,\n"
        )
        result = analyze(csv_bytes)
        self.assertEqual(
            sorted(e.employee_id for e in result.cyclic_employees), ["DIV-1", "DIV-2"]
        )

    def test_malformed_upload_raises(self):
        with self.assertRaises(HrisError):
            analyze(b"not a csv at all, no headers\n")

    def test_duplicated_identity_rows_excluded_from_hierarchy(self):
        csv_bytes = (
            b"employee_id,employee_name,email,manager_id,manager_email,department\n"
            b"DIV-1,A,a@y.com,,,\n"
            b"DIV-1,A,a@y.com,DIV-1,,\n"  # duplicate id
        )
        result = analyze(csv_bytes)
        self.assertEqual(len(result.accepted_employees), 0)
        # 2 rows x 2 errors each (id dup + email dup) = 4
        self.assertEqual(len(result.validation_errors), 4)


if __name__ == "__main__":
    unittest.main()
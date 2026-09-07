"""Regression coverage for failure handling in the type-check gate."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "type_gate", Path(__file__).parents[1] / "check-types.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class TypeGateTests(unittest.TestCase):
    def test_replacement_diagnostic_cannot_hide_behind_same_count(self):
        new, stale = gate.compare([["new"]], [["old"]])
        self.assertEqual(new, [("new",)])
        self.assertEqual(stale, [("old",)])

    def test_duplicate_diagnostics_are_counted(self):
        self.assertEqual(gate.compare([["x"], ["x"]], [["x"]])[0], [("x",)])

    def test_fixed_issues_require_removing_old_exemptions(self):
        self.assertEqual(gate.compare([], [["old"]]), ([], [("old",)]))

    def test_crashing_checker_is_not_an_empty_success(self):
        with (
            patch.object(
                gate.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=2, stderr="crash", stdout="[]"),
            ),
            self.assertRaises(RuntimeError),
        ):
            gate.main()

    def test_empty_output_with_failure_is_rejected(self):
        with (
            patch.object(
                gate.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stderr="", stdout="[]"),
            ),
            self.assertRaises(RuntimeError),
        ):
            gate.main()

    def test_malformed_report_is_rejected(self):
        with self.assertRaises(ValueError):
            gate.normalize({"unexpected": "schema"})


if __name__ == "__main__":
    unittest.main()

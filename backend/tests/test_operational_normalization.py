"""Standalone tests for deterministic operational-evidence normalization.

Run without pytest from the repository root:

    python3 backend/tests/test_operational_normalization.py
"""

import sys
from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.operational_normalization import (  # noqa: E402
    canonicalize_timestamp,
    convert_value,
    normalize_operational_evidence_row,
    suggest_measurement_columns,
    suggest_schema_mapping,
)


class OperationalNormalizationTest(unittest.TestCase):
    def test_schema_aids_only_apply_explicit_aliases(self):
        aids = suggest_schema_mapping(["Asset ID", "Machine Identifier", "Recorded At"])

        self.assertEqual(aids["suggested_mapping"]["Asset ID"], "asset_id")
        self.assertEqual(aids["suggested_mapping"]["Recorded At"], "event_time")
        self.assertIn("Machine Identifier", aids["unmapped_headers"])

        measurements = suggest_measurement_columns(["Temperature (°F)", "energy_kwh"])
        self.assertEqual(
            measurements,
            [
                {
                    "source_header": "energy_kwh",
                    "metric_name": "energy",
                    "unit": "kWh",
                    "dimension": "energy",
                    "confidence": "explicit_header_unit",
                },
                {
                    "source_header": "Temperature (°F)",
                    "metric_name": "temperature",
                    "unit": "degF",
                    "dimension": "temperature",
                    "confidence": "explicit_header_unit",
                },
            ],
        )

    def test_common_dimension_conversions_and_dimension_guard(self):
        cases = (
            (212, "degF", "degC", 100),
            (1, "km", "m", 1000),
            (1000, "g", "kg", 1),
            (3600000, "J", "kWh", 1),
            (1, "bar", "kPa", 100),
        )
        for value, source, target, expected in cases:
            with self.subTest(source=source):
                result = convert_value(value, source, target)
                self.assertTrue(result.success)
                self.assertEqual(result.value, expected)
                self.assertEqual(result.to_unit, target)

        incompatible = convert_value(1, "kg", "m")
        self.assertFalse(incompatible.success)
        self.assertEqual(incompatible.reason_code, "incompatible_unit_dimension")

    def test_normalizes_long_form_row_and_records_conversion(self):
        result = normalize_operational_evidence_row(
            {
                "Machine ID": "MX-101",
                "Recorded At": "2026-07-08T12:00:00-07:00",
                "Metric": "bearing_temperature",
                "Reading Value": 68,
                "Unit": "°F",
            }
        )

        self.assertEqual(
            result.normalized_row,
            {
                "asset_id": "MX-101",
                "event_time": "2026-07-08T19:00:00Z",
                "metric_name": "bearing_temperature",
                "value": 20,
                "unit": "degC",
            },
        )
        self.assertEqual(result.conversions[0].dimension, "temperature")
        self.assertTrue(result.quality.valid)
        self.assertEqual(result.quality.score, 100)
        self.assertEqual(result.quality.disposition, "accept")

    def test_header_unit_is_usable_only_when_no_explicit_unit_conflicts(self):
        source = {
            "Asset ID": "MX-102",
            "Timestamp": "2026-07-08T19:00:00Z",
            "Metric": "bearing_temperature",
            "Temperature (°F)": 68,
        }
        inferred = normalize_operational_evidence_row(
            source,
            field_mapping={"Temperature (°F)": "value"},
        )
        self.assertEqual(inferred.normalized_row["value"], 20)
        self.assertEqual(inferred.normalized_row["unit"], "degC")

        unknown_explicit = normalize_operational_evidence_row(
            {**source, "Unit": "vendor_temperature_scale"},
            field_mapping={"Temperature (°F)": "value"},
        )
        self.assertEqual(unknown_explicit.normalized_row["value"], 68)
        self.assertEqual(unknown_explicit.normalized_row["unit"], "vendor_temperature_scale")
        self.assertIn("unknown_unit", [issue.code for issue in unknown_explicit.quality.issues])
        self.assertEqual(unknown_explicit.quality.disposition, "review")

        conflicting_explicit = normalize_operational_evidence_row(
            {**source, "Unit": "degC"},
            field_mapping={"Temperature (°F)": "value"},
        )
        self.assertEqual(conflicting_explicit.normalized_row["value"], 68)
        self.assertIn("unit_conflict", [issue.code for issue in conflicting_explicit.quality.issues])
        self.assertFalse(conflicting_explicit.quality.valid)
        self.assertEqual(conflicting_explicit.quality.disposition, "reject")

    def test_timestamp_assumptions_are_explicit_and_dst_is_safe(self):
        naive = canonicalize_timestamp(
            "2026-07-08T12:00:00", assumed_timezone="America/Los_Angeles"
        )
        self.assertTrue(naive.success)
        self.assertEqual(naive.canonical_timestamp, "2026-07-08T19:00:00Z")
        self.assertIn("naive_timestamp_assumed_timezone", naive.warning_codes)
        self.assertIn("America/Los_Angeles", naive.timezone_assumption or "")

        ambiguous = canonicalize_timestamp(
            "2026-11-01T01:30:00", assumed_timezone="America/Los_Angeles"
        )
        self.assertFalse(ambiguous.success)
        self.assertEqual(ambiguous.error_code, "ambiguous_local_time")

        resolved = canonicalize_timestamp(
            "2026-11-01T01:30:00",
            assumed_timezone="America/Los_Angeles",
            naive_fold=1,
        )
        self.assertTrue(resolved.success)
        self.assertEqual(resolved.canonical_timestamp, "2026-11-01T09:30:00Z")
        self.assertIn("ambiguous_local_time_resolved", resolved.warning_codes)

        nonexistent = canonicalize_timestamp(
            "2026-03-08T02:30:00", assumed_timezone="America/Los_Angeles"
        )
        self.assertFalse(nonexistent.success)
        self.assertEqual(nonexistent.error_code, "nonexistent_local_time")


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""
Extreme Edge Cases & Malformed Payload Test Suite: rvtools-migration-planner

Validates engine resilience against corrupted Excel archives, malformed XML,
truncated CSVs, ReDoS payloads, zero-width Unicode injection, negative hardware
metrics, and boundary conditions.

Adheres strictly to Workspace Rule 7 (Zero-Emoji Enterprise Tone) and
Rule 9 (Automated Test Harness with 100% Synthetic Mock Data).
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# Add scripts directory to module import path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from rvtools_planner import (
    Sanitizer,
    MigrationEngine,
    MigrationReportGenerator,
    RVToolsParser,
    VirtualMachine,
    DiskInfo,
    SnapshotInfo,
)


class TestExtremeEdgeCases(unittest.TestCase):
    """Extreme edge case tests covering corrupt data and hostile inputs."""

    def setUp(self) -> None:
        self.sanitizer = Sanitizer(salt="test-extreme-salt")
        self.engine = MigrationEngine(sanitizer=self.sanitizer)
        self.generator = MigrationReportGenerator(sanitizer=self.sanitizer)
        self.parser = RVToolsParser()

    def test_nonexistent_file_handling(self) -> None:
        """Ensures non-existent paths raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.parser.parse("non_existent_file_path_12345.xlsx")

    def test_unsupported_file_extension(self) -> None:
        """Ensures unsupported file extensions raise ValueError."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"Hello World")
            path = tf.name
        try:
            with self.assertRaises(ValueError) as ctx:
                self.parser.parse(path)
            self.assertIn("Unsupported file format", str(ctx.exception))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_corrupted_zip_file_handling(self) -> None:
        """Ensures corrupt xlsx (invalid zip) produces empty sheets or warning without crashing."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            tf.write(b"NOT_A_VALID_ZIP_HEADER_DATA_STREAM")
            path = tf.name
        try:
            sheets = self.parser.parse(path)
            self.assertEqual(sheets, {})
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_xlsx_missing_workbook_xml(self) -> None:
        """Validates handling when xl/workbook.xml is absent inside zip."""
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("xl/sharedStrings.xml", "<sst><si><t>Test</t></si></sst>")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            tf.write(bio.getvalue())
            path = tf.name
        try:
            sheets = self.parser.parse(path)
            self.assertEqual(sheets, {})
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_empty_and_whitespace_only_csv(self) -> None:
        """Ensures empty or pure whitespace CSV files produce empty list without crash."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tf:
            tf.write("\n   \r\n\t  \n")
            path = tf.name
        try:
            rows = self.parser._read_csv_file(Path(path))
            self.assertEqual(rows, [])
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_csv_mismatched_columns(self) -> None:
        """Parses rows where column counts exceed or fall short of the header."""
        csv_content = (
            "VM,Powerstate,CPUs\n"
            "mock-ragged-vm-01,poweredOn,8,EXTRA_UNMAPPED_COLUMN,MORE_DATA\n"
            "mock-ragged-vm-02\n"
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tf:
            tf.write(csv_content)
            path = tf.name
        try:
            rows = self.parser._read_csv_file(Path(path))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["VM"], "mock-ragged-vm-01")
            self.assertEqual(rows[1]["VM"], "mock-ragged-vm-02")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_redos_pattern_resilience(self) -> None:
        """Verifies IP regex does not freeze or trigger catastrophic backtracking."""
        pathological_string = "255." * 5000 + "999"
        sanitized = self.sanitizer.scrub_text(pathological_string)
        self.assertTrue(len(sanitized) > 0)

    def test_unicode_and_zero_width_injection(self) -> None:
        """Verifies zero-width spaces, right-to-left marks, and non-ASCII characters."""
        hostile_name = "mock-vm\u200b\u200c\u200d-test\ufeff\u202eEXE.DOC"
        scrubbed = self.sanitizer.scrub_text(hostile_name)
        self.assertNotIn("\u200b", scrubbed)
        self.assertNotIn("\ufeff", scrubbed)

        assessment = self.engine.analyze({
            "vInfo": [{
                "VM": hostile_name,
                "Powerstate": "poweredOn",
                "CPUs": "4",
                "Memory": "8192",
                "OS according to the VM spec": "Ubuntu Linux (64-bit)"
            }]
        })
        self.assertEqual(assessment.total_vms, 1)
        self.assertEqual(assessment.powered_on_vms, 1)

    def test_negative_and_nan_metrics_defense(self) -> None:
        """Guards against negative, NaN, or non-numeric values in hardware specifications."""
        corrupt_vinfo = [
            {
                "VM": "mock-negative-vm",
                "Powerstate": "poweredOn",
                "CPUs": "-8",
                "Memory": "-16384",
                "Provisioned MiB": "NaN",
                "In Use MiB": "None",
                "OS according to the configuration file": "Microsoft Windows Server 2022"
            }
        ]
        assessment = self.engine.analyze({"vInfo": corrupt_vinfo})
        self.assertEqual(assessment.total_vms, 1)
        vm = assessment.vms[0]
        self.assertGreaterEqual(vm.cpus, 0)
        self.assertGreaterEqual(vm.memory_mb, 0)
        self.assertGreaterEqual(vm.provisioned_gb, 0.0)
        self.assertGreaterEqual(vm.in_use_gb, 0.0)

    def test_malformed_snapshot_dates(self) -> None:
        """Tests snapshot date parser against unexpected formats and unparseable strings."""
        corrupt_vinfo = [{"VM": "mock-snap-vm", "Powerstate": "poweredOn", "CPUs": "2", "Memory": "4096"}]
        corrupt_vsnap = [
            {
                "VM": "mock-snap-vm",
                "Snapshot": "bad-date-snapshot",
                "Snapshot Date / Time": "INVALID_DATE_TIME_STRING_31-02-2025 99:99",
                "Size MiB": "51200"
            },
            {
                "VM": "mock-snap-vm",
                "Snapshot": "empty-date-snapshot",
                "Snapshot Date / Time": "",
                "Size MiB": "10240"
            }
        ]
        assessment = self.engine.analyze({"vInfo": corrupt_vinfo, "vSnapshot": corrupt_vsnap})
        self.assertEqual(assessment.total_vms, 1)
        vm = assessment.vms[0]
        self.assertEqual(len(vm.snapshots), 2)

    def test_extreme_vm_name_lengths(self) -> None:
        """Handles 5,000-character VM names without truncation crashes."""
        massive_name = "mock-vm-" + ("a" * 5000)
        assessment = self.engine.analyze({"vInfo": [{
            "VM": massive_name,
            "Powerstate": "poweredOn",
            "CPUs": "2",
            "Memory": "4096",
            "Provisioned MiB": "10240",
            "In Use MiB": "5120",
            "OS according to the VM spec": "CentOS 7 (64-bit)"
        }]})
        self.assertEqual(assessment.total_vms, 1)
        self.assertEqual(assessment.vms[0].name, massive_name)
        markdown = self.generator.generate_markdown(assessment)
        self.assertTrue(len(markdown) > 100)

    def test_directory_csv_with_missing_optional_tabs(self) -> None:
        """Parses directory containing only vInfo.csv and missing vDisk, vSnapshot, vHost."""
        with tempfile.TemporaryDirectory() as td:
            vinfo_file = Path(td) / "vInfo.csv"
            vinfo_file.write_text("VM,Powerstate,CPUs,Memory\nmock-solo-vm,poweredOn,4,8192\n", encoding="utf-8")
            data = self.parser._parse_csv_directory(Path(td))
            self.assertIn("vInfo", data)
            self.assertEqual(len(data["vInfo"]), 1)
            self.assertNotIn("vDisk", data)
            self.assertNotIn("vSnapshot", data)

    def test_zero_vms_empty_datacenter(self) -> None:
        """Tests assessment generation on an empty cluster without div-by-zero errors."""
        assessment = self.engine.analyze({"vInfo": []})
        self.assertEqual(assessment.total_vms, 0)
        self.assertEqual(assessment.readiness_percentage, 100.0)
        markdown = self.generator.generate_markdown(assessment)
        self.assertIn("100.0%", markdown)


if __name__ == "__main__":
    unittest.main()

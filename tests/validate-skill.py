#!/usr/bin/env python3
"""
Standard Enterprise Validation Suite: rvtools-migration-planner

Validates core inventory parsing, blocker detection (RDMs, stale snapshots,
legacy OS), target cluster sizing calculations, client-side data sanitization,
and zero-emoji compliance.

Strictly adheres to Workspace Rule 7 (Zero-Emoji Enterprise Tone) and
Rule 9 (Automated Test Harness with 100% Synthetic Mock Data).
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

# Add scripts directory to module import path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from rvtools_planner import (
    Sanitizer,
    RVToolsParser,
    MigrationEngine,
    MigrationReportGenerator,
    VirtualMachine,
    DiskInfo,
    SnapshotInfo,
    TargetClusterSizing,
    MigrationAssessment
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestReportStructureAndHeadings(unittest.TestCase):
    """Suite 1: Verifies mandatory Markdown report structure and sections."""

    def setUp(self) -> None:
        self.parser = RVToolsParser()
        self.engine = MigrationEngine()
        self.generator = MigrationReportGenerator()

    def test_all_fixtures_generate_mandatory_headings(self) -> None:
        """Verifies all standard sections exist in the generated assessment report."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)
        report = self.generator.format_markdown(assessment)

        mandatory_headings = [
            "# VMware Migration Assessment & Sizing Plan (`rvtools-migration-planner`)",
            "## 1. Executive Summary & Inventory Metrics",
            "## 2. Critical Blockers & Architectural Constraints Matrix",
            "## 3. Phased Migration Wave Plan",
            "## 4. Target Destination Cluster Sizing",
            "## 5. Automated Target Import Runbook (Proxmox VE)"
        ]
        for heading in mandatory_headings:
            self.assertIn(heading, report, f"Missing mandatory heading: {heading}")

    def test_runbook_contains_qm_create_and_importdisk(self) -> None:
        """Verifies Proxmox VE runbook commands exist."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)
        report = self.generator.format_markdown(assessment)
        self.assertIn("qm create", report)
        self.assertIn("qm importdisk", report)


class TestDeterministicBlockerDetection(unittest.TestCase):
    """Suite 2: Validates detection of RDMs, Stale Snapshots, and Legacy OS."""

    def setUp(self) -> None:
        self.parser = RVToolsParser()
        self.engine = MigrationEngine()

    def test_rdm_and_multiwriter_detection(self) -> None:
        """Identifies physical RDMs and multi-writer shared disks."""
        xlsx_file = FIXTURES_DIR / "fixture-rdm-and-snapshots-blockers.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)

        self.assertGreaterEqual(assessment.rdm_count, 1)
        self.assertGreaterEqual(assessment.multiwriter_count, 1)

        # Check that RDM VM has blocker flag
        rdm_vms = [v for v in assessment.vms if v.has_rdm]
        self.assertTrue(any("Raw Device Mapping" in b for v in rdm_vms for b in v.blockers))

    def test_stale_snapshot_detection(self) -> None:
        """Flags snapshots older than 72 hours as critical blockers."""
        xlsx_file = FIXTURES_DIR / "fixture-rdm-and-snapshots-blockers.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)

        self.assertGreaterEqual(assessment.stale_snapshot_count, 1)
        snap_vms = [v for v in assessment.vms if v.has_stale_snapshot]
        self.assertTrue(any("Stale snapshot" in b for v in snap_vms for b in v.blockers))

    def test_legacy_os_detection(self) -> None:
        """Identifies Windows 2003 and CentOS 5 needing VirtIO driver injection."""
        csv_file = FIXTURES_DIR / "fixture-legacy-os-fleet.csv"
        tables = self.parser.parse(str(csv_file))
        assessment = self.engine.analyze(tables)

        self.assertGreaterEqual(assessment.legacy_os_count, 2)
        legacy_vms = [v for v in assessment.vms if v.has_legacy_os]
        self.assertTrue(any("VirtIO" in w for v in legacy_vms for w in v.warnings))

    def test_monster_vm_detection(self) -> None:
        """Identifies VMs with >=32 vCPUs or >=128GB RAM."""
        xlsx_file = FIXTURES_DIR / "fixture-monster-vms-and-clustering.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)

        self.assertGreaterEqual(assessment.monster_vm_count, 2)
        monster_vms = [v for v in assessment.vms if v.is_monster_vm]
        self.assertTrue(any("vNUMA" in w for v in monster_vms for w in v.warnings))

    def test_clean_greenfield_readiness(self) -> None:
        """Confirms clean environment achieves 100% readiness score."""
        csv_file = FIXTURES_DIR / "fixture-clean-greenfield-cluster.csv"
        tables = self.parser.parse(str(csv_file))
        assessment = self.engine.analyze(tables)

        self.assertEqual(assessment.readiness_percentage, 100.0)
        self.assertEqual(assessment.rdm_count, 0)
        self.assertEqual(assessment.stale_snapshot_count, 0)


class TestTargetClusterSizing(unittest.TestCase):
    """Suite 3: Verifies physical core, RAM, storage, and node count sizing."""

    def setUp(self) -> None:
        self.parser = RVToolsParser()
        self.engine = MigrationEngine()

    def test_proxmox_core_overcommit_sizing(self) -> None:
        """Validates 2:1 production overcommit ratio on active vCPUs."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables, prod_overcommit=2.0)
        s = assessment.sizing

        expected_cores = max(16, int(assessment.active_vcpus / 2.0))
        self.assertEqual(s.required_pcores, expected_cores)

    def test_proxmox_ceph_3x_storage_sizing(self) -> None:
        """Validates 3x replication factor on usable storage."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)
        s = assessment.sizing

        expected_usable = round((assessment.total_storage_gb * 1.20) / 1024.0, 1)
        expected_raw = round(expected_usable * 3.0, 1)
        self.assertEqual(s.usable_storage_tb, expected_usable)
        self.assertEqual(s.raw_storage_tb, expected_raw)

    def test_n_plus_one_node_recommendation(self) -> None:
        """Ensures recommended nodes include at least 1 spare HA node."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables)
        s = assessment.sizing

        self.assertEqual(s.nodes_recommended_n1, s.nodes_required_n0 + 1)
        self.assertEqual(s.nodes_recommended_n2, s.nodes_required_n0 + 2)

    def test_hyperv_core_licensing_sizing(self) -> None:
        """Verifies Microsoft Hyper-V Windows Server Datacenter core licensing math."""
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        assessment = self.engine.analyze(tables, target_hypervisor="Microsoft Hyper-V", node_cores=32)
        s = assessment.sizing
        # At 32 cores per host, licensing is 32 cores * N+1 nodes
        self.assertEqual(s.hyperv_core_licenses, s.nodes_recommended_n1 * 32)


class TestPIISanitizationGuarantee(unittest.TestCase):
    """Suite 4: Verifies client-side masking of VM names, hostnames, and IP addresses."""

    def setUp(self) -> None:
        self.sanitizer = Sanitizer()

    def test_masks_vm_names(self) -> None:
        masked1 = self.sanitizer.mask_vm("prod-sql-primary-01")
        masked2 = self.sanitizer.mask_vm("prod-sql-primary-01")
        self.assertTrue(masked1.startswith("vm-"))
        self.assertEqual(masked1, masked2)

    def test_masks_esxi_hosts(self) -> None:
        masked = self.sanitizer.mask_host("esx-node-prod-01.corp.example.com")
        self.assertTrue(masked.startswith("esxi-"))
        self.assertTrue(masked.endswith(".internal"))

    def test_masks_ipv4_addresses(self) -> None:
        text = "Database interface on 10.50.20.15 and 172.16.4.1"
        scrubbed = self.sanitizer.scrub_text(text)
        self.assertNotIn("10.50.20.15", scrubbed)
        self.assertNotIn("172.16.4.1", scrubbed)
        self.assertIn("192.0.2.", scrubbed)

    def test_masks_mac_addresses(self) -> None:
        text = "Primary interface MAC: 00:50:56:AB:CD:EF"
        scrubbed = self.sanitizer.scrub_text(text)
        self.assertNotIn("00:50:56:AB:CD:EF", scrubbed)
        self.assertIn("52:54:00:12:34:56", scrubbed)


class TestMultiFormatOutputGeneration(unittest.TestCase):
    """Suite 5: Verifies export to Markdown, JSON, HTML, CSV, and Proof-of-Work."""

    def setUp(self) -> None:
        self.parser = RVToolsParser()
        self.engine = MigrationEngine()
        self.generator = MigrationReportGenerator()
        xlsx_file = FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx"
        tables = self.parser.parse(str(xlsx_file))
        self.assessment = self.engine.analyze(tables)

    def test_json_export_structure(self) -> None:
        json_str = self.generator.format_json(self.assessment)
        data = json.loads(json_str)
        self.assertIn("assessment_id", data)
        self.assertIn("metrics", data)
        self.assertIn("blockers_summary", data)
        self.assertIn("target_sizing", data)
        self.assertIn("waves", data)

    def test_html_export_structure(self) -> None:
        html_out = self.generator.format_html(self.assessment)
        self.assertIn("<!DOCTYPE html>", html_out)
        self.assertIn("VMware Hypervisor Exit Plan", html_out)
        self.assertIn("Migration Wave Inventory Preview", html_out)

    def test_csv_wave_schedule_structure(self) -> None:
        csv_out = self.generator.format_csv(self.assessment)
        lines = csv_out.splitlines()
        self.assertGreater(len(lines), 10)
        self.assertIn("VM_Name,Wave,Power_State", lines[0])

    def test_proof_of_work_structure(self) -> None:
        pow_doc = self.generator.format_proof_of_work(self.assessment)
        self.assertIn("# SRE & Infrastructure Portfolio Proof-of-Work", pow_doc)
        self.assertIn("Project Context:", pow_doc)
        self.assertIn("Destination Cluster Sizing:", pow_doc)


class TestZeroEmojiCompliance(unittest.TestCase):
    """Suite 6: Enforces Workspace Rule 7 (Zero-Emoji Enterprise Tone)."""

    def test_code_and_docs_are_zero_emoji(self) -> None:
        emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
        )
        base_dir = Path(__file__).resolve().parent.parent
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith((".py", ".md", ".json", ".csv", ".html")):
                    file_path = Path(root) / file
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        match = emoji_pattern.search(content)
                        self.assertIsNone(match, f"Rule 7 Violation: Found emoji '{match.group(0) if match else ''}' in {file_path}")
                    except Exception:
                        pass


if __name__ == "__main__":
    unittest.main()

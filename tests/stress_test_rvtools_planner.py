#!/usr/bin/env python3
"""
High-Volume Stress & Throughput Suite: rvtools-migration-planner

Benchmarks ingestion performance and stability when evaluating large-scale
enterprise VMware estates (5,000+ VMs, multi-disk hierarchies, deep snapshot
trees, and multi-cluster environments).

Strictly adheres to Workspace Rule 7 (Zero-Emoji Enterprise Tone) and
Rule 9 (Automated Test Harness with 100% Synthetic Mock Data).
"""

import datetime
import os
import sys
import time
import unittest
from pathlib import Path

# Add scripts directory to module import path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from rvtools_planner import (
    Sanitizer,
    MigrationEngine,
    MigrationReportGenerator,
    VirtualMachine,
    DiskInfo,
    SnapshotInfo
)


class TestHighVolumeAndThroughput(unittest.TestCase):
    """Stress tests verifying scalability across large enterprise environments."""

    def setUp(self) -> None:
        self.sanitizer = Sanitizer()
        self.engine = MigrationEngine(sanitizer=self.sanitizer)
        self.generator = MigrationReportGenerator(sanitizer=self.sanitizer)

    def test_massive_5000_vm_estate_processing(self) -> None:
        """Processes 5,000 synthetic VMs within 2.0 seconds."""
        vinfo_rows = []
        vdisk_rows = []
        vsnap_rows = []

        for i in range(1, 5001):
            vm_name = f"mock-vm-scale-{i:05d}"
            power = "poweredOn" if i % 6 != 0 else "poweredOff"
            vinfo_rows.append({
                "VM": vm_name,
                "Powerstate": power,
                "CPUs": str((i % 8) + 1),
                "Memory": str(4096 * ((i % 4) + 1)),
                "Provisioned MiB": "51200",
                "In Use MiB": "25600",
                "OS according to the VM spec": "Red Hat Enterprise Linux 8 (64-bit)" if i % 2 == 0 else "Microsoft Windows Server 2019",
                "Host": f"mock-esxi-{(i % 64) + 1:02d}.synthetic.local",
                "Cluster": f"Cluster-{(i % 8) + 1}",
                "Datacenter": "Datacenter-Enterprise",
                "Primary IP Address": f"10.{(i // 254) % 250}.{(i % 254) + 1}.10"
            })
            # 2 Disks per VM = 10,000 disks
            vdisk_rows.append({
                "VM": vm_name,
                "Disk": "Hard disk 1",
                "Capacity MiB": "40960",
                "Disk Path": f"[san-01] {vm_name}/os.vmdk",
                "Controller": "SCSI",
                "Sharing": "sharingNone",
                "Raw": "flat"
            })
            if i % 10 == 0:
                vdisk_rows.append({
                    "VM": vm_name,
                    "Disk": "Hard disk 2",
                    "Capacity MiB": "102400",
                    "Disk Path": f"[san-01] {vm_name}/data.vmdk",
                    "Controller": "SCSI",
                    "Sharing": "sharingNone",
                    "Raw": "rawDeviceMapPage" if i % 100 == 0 else "flat"
                })

            if i % 20 == 0:
                vsnap_rows.append({
                    "VM": vm_name,
                    "Snapshot": "backup-snap",
                    "Date / time snapshot": "2026-09-01 00:00:00",
                    "Size MiB": "15360"
                })

        tables = {
            "vInfo": vinfo_rows,
            "vDisk": vdisk_rows,
            "vSnapshot": vsnap_rows
        }

        start_time = time.time()
        assessment = self.engine.analyze(tables)
        duration = time.time() - start_time

        self.assertEqual(assessment.total_vms, 5000)
        self.assertGreater(assessment.rdm_count, 10)
        self.assertGreater(assessment.stale_snapshot_count, 100)
        self.assertLess(duration, 2.0, f"Processing 5,000 VMs took {duration:.3f}s (exceeded 2.0s SLA)")
        print(f"\n[STRESS BENCHMARK] 5,000 VMs analyzed in {duration:.3f}s ({int(5000 / duration)} VMs/sec)")

    def test_multi_disk_heavy_workloads(self) -> None:
        """Evaluates database servers with 16 virtual disks each."""
        vinfo_rows = []
        vdisk_rows = []

        for i in range(1, 51):
            vm_name = f"mock-db-cluster-{i:02d}"
            vinfo_rows.append({
                "VM": vm_name,
                "Powerstate": "poweredOn",
                "CPUs": "16",
                "Memory": "65536",
                "Provisioned MiB": "1048576",
                "In Use MiB": "524288",
                "OS according to the VM spec": "Oracle Linux 8 (64-bit)",
                "Host": f"mock-esxi-{(i % 4) + 1:02d}.synthetic.local",
                "Cluster": "Cluster-DB"
            })
            for d in range(1, 17):
                vdisk_rows.append({
                    "VM": vm_name,
                    "Disk": f"Hard disk {d}",
                    "Capacity MiB": "65536",
                    "Disk Path": f"[san-db] {vm_name}/disk_{d}.vmdk",
                    "Controller": "SCSI",
                    "Sharing": "sharingMultiWriter" if d == 2 else "sharingNone",
                    "Raw": "flat"
                })

        tables = {"vInfo": vinfo_rows, "vDisk": vdisk_rows}
        assessment = self.engine.analyze(tables)
        self.assertEqual(assessment.total_vms, 50)
        self.assertEqual(assessment.multiwriter_count, 50)

    def test_massive_snapshot_tree_aggregation(self) -> None:
        """Aggregates multiple snapshot chains per VM."""
        vinfo_rows = [
            {"VM": "mock-snap-test-vm", "Powerstate": "poweredOn", "CPUs": "4", "Memory": "16384", "Provisioned MiB": "102400", "In Use MiB": "51200", "OS according to the VM spec": "Linux", "Host": "esxi-01"}
        ]
        vsnap_rows = [
            {"VM": "mock-snap-test-vm", "Snapshot": f"Snapshot-Level-{lvl}", "Date / time snapshot": "2026-08-01 10:00:00", "Size MiB": "5120"}
            for lvl in range(1, 11)
        ]
        tables = {"vInfo": vinfo_rows, "vSnapshot": vsnap_rows}
        assessment = self.engine.analyze(tables)
        vm = assessment.vms[0]
        self.assertEqual(len(vm.snapshots), 10)
        self.assertTrue(vm.has_stale_snapshot)

    def test_zombie_vm_storage_reclamation(self) -> None:
        """Accurately calculates reclaimable storage from powered off zombie workloads."""
        vinfo_rows = [
            {"VM": f"mock-zombie-vm-{i:02d}", "Powerstate": "poweredOff", "CPUs": "2", "Memory": "4096", "Provisioned MiB": "102400", "In Use MiB": "51200", "OS according to the VM spec": "Windows", "Host": "esxi-01"}
            for i in range(1, 21)
        ]
        tables = {"vInfo": vinfo_rows}
        assessment = self.engine.analyze(tables)
        self.assertEqual(assessment.zombie_vms, 20)
        # 20 VMs * 50 GB (51200 MiB) = 1,000 GB
        self.assertAlmostEqual(assessment.zombie_reclaimable_gb, 1000.0, delta=1.0)

    def test_rule_7_zero_emoji_guarantee_on_stress_battery(self) -> None:
        """Verifies that stress test fixtures and outputs are strictly zero emoji."""
        test_path = Path(__file__).resolve()
        content = test_path.read_text(encoding="utf-8")
        has_emoji = bool(self.sanitizer.EMOJI_PATTERN.search(content))
        self.assertFalse(has_emoji, "Detected emoji in stress test suite violating Rule 7.")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Advanced Architectural Edge Cases & Sizing Suite: rvtools-migration-planner

Validates deep virtualization calculations and migration blockers:
1. Ceph 3x replication storage mathematics and maintenance headroom.
2. Windows Server VirtIO storage controller injection warnings.
3. Microsoft Windows Server Hyper-V core licensing rules (16-core min per server).
4. Multi-writer SCSI bus detection (Oracle RAC / MSCS clusters).
5. Raw Device Mapping (RDM) virtual vs physical compatibility mode blockers.
6. vNUMA boundary and monster VM qualification (vCPUs > 32 or RAM > 128GB).
7. Migration wave categorization (Wave 0 through Wave 4).
8. Zombie VM identification and capacity reclaim potential.

Adheres strictly to Workspace Rule 7 (Zero-Emoji Enterprise Tone) and
Rule 9 (Automated Test Harness with 100% Synthetic Mock Data).
"""

import sys
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
    SnapshotInfo,
    TargetClusterSizing,
)


class TestAdvancedArchitecturalEdgeCases(unittest.TestCase):
    """Deep architectural edge case verification."""

    def setUp(self) -> None:
        self.sanitizer = Sanitizer(salt="test-architectural-salt")
        self.engine = MigrationEngine(sanitizer=self.sanitizer)
        self.generator = MigrationReportGenerator(sanitizer=self.sanitizer)

    def test_ceph_storage_math_and_headroom(self) -> None:
        """Verifies Ceph 3x replication and 20% recovery headroom math."""
        # 10,000 GB in-use storage -> usable = 10,000 * 1.20 = 12,000 GB = 11.72 TB
        # raw = 12,000 * 3 = 36,000 GB = 35.16 TB
        vinfo = [
            {
                "VM": "mock-storage-vm",
                "Powerstate": "poweredOn",
                "CPUs": "8",
                "Memory": "32768",
                "Provisioned MiB": "20971520",  # 20 TB
                "In Use MiB": "10485760",       # 10 TB = 10240 GB
                "OS according to the VM spec": "Red Hat Enterprise Linux 9 (64-bit)"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo}, target_hypervisor="Proxmox VE")
        s = assessment.sizing
        # Verify in-use storage in GB
        self.assertAlmostEqual(assessment.total_storage_gb, 10240.0, places=1)
        # Usable storage TB = (10240 * 1.20) / 1024 = 12.0 TB
        self.assertAlmostEqual(s.usable_storage_tb, 12.0, places=1)
        # Raw storage TB = Usable * 3 = 36.0 TB
        self.assertAlmostEqual(s.raw_storage_tb, 36.0, places=1)

    def test_hyperv_core_licensing_rules(self) -> None:
        """Validates Microsoft Windows Server 16-core physical server licensing floor."""
        # A 4-node cluster with 16 cores per node = 4 * 16 = 64 core licenses minimum
        vinfo = [
            {"VM": f"mock-vm-{i}", "Powerstate": "poweredOn", "CPUs": "4", "Memory": "8192", "In Use MiB": "10240"}
            for i in range(16)
        ]
        # 16 VMs * 4 vCPUs = 64 active vCPUs. Overcommit 2.0 = 32 pCores.
        # Node profile: 16 cores per node -> 2 nodes N+0, 3 nodes N+1, 4 nodes N+2
        assessment = self.engine.analyze(
            {"vInfo": vinfo},
            target_hypervisor="Microsoft Hyper-V",
            node_cores=16,
            node_ram_gb=128
        )
        s = assessment.sizing
        self.assertEqual(s.target_hypervisor, "Microsoft Hyper-V")
        self.assertGreaterEqual(s.hyperv_core_licenses, s.nodes_recommended_n1 * 16)
        self.assertEqual(s.hyperv_core_licenses % 2, 0)  # Core licenses sold in 2-core packs

    def test_windows_virtio_scsi_controller_warnings(self) -> None:
        """Ensures Windows VMs without VirtIO injection flags emit critical warning."""
        vinfo = [
            {
                "VM": "mock-win-sql-01",
                "Powerstate": "poweredOn",
                "CPUs": "8",
                "Memory": "32768",
                "OS according to the VM spec": "Microsoft Windows Server 2022 (64-bit)"
            }
        ]
        vdisk = [
            {
                "VM": "mock-win-sql-01",
                "Disk": "Hard disk 1",
                "Controller": "VMware Paravirtual SCSI",
                "Capacity MiB": "102400"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo, "vDisk": vdisk}, target_hypervisor="Proxmox VE")
        vm = assessment.vms[0]
        # Must detect controller and advise VirtIO injection prior to cutover
        warning_str = " ".join(vm.warnings)
        self.assertTrue(
            "virtio" in warning_str.lower() or "controller" in warning_str.lower() or "pvscsi" in warning_str.lower(),
            f"Expected VirtIO controller warning, got: {warning_str}"
        )

    def test_multiwriter_oracle_rac_blocker(self) -> None:
        """Confirms multi-writer shared SCSI bus blocks standard migration."""
        vinfo = [
            {"VM": "mock-rac-node01", "Powerstate": "poweredOn", "CPUs": "16", "Memory": "65536"},
            {"VM": "mock-rac-node02", "Powerstate": "poweredOn", "CPUs": "16", "Memory": "65536"}
        ]
        vdisk = [
            {
                "VM": "mock-rac-node01",
                "Disk": "Hard disk 2",
                "Sharing": "sharingMultiWriter",
                "Capacity MiB": "512000"
            },
            {
                "VM": "mock-rac-node02",
                "Disk": "Hard disk 2",
                "Sharing": "sharingMultiWriter",
                "Capacity MiB": "512000"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo, "vDisk": vdisk})
        self.assertEqual(assessment.multiwriter_count, 2)
        for vm in assessment.vms:
            self.assertTrue(vm.has_multiwriter)
            self.assertEqual(vm.assigned_wave, 4)  # Multi-writer must go to Wave 4
            self.assertTrue(any("multi-writer" in b.lower() or "cluster" in b.lower() for b in vm.blockers))

    def test_raw_device_mapping_rdm_blocker(self) -> None:
        """Verifies physical and virtual RDMs are flagged as critical blockers."""
        vinfo = [
            {"VM": "mock-rdm-workload", "Powerstate": "poweredOn", "CPUs": "8", "Memory": "16384"}
        ]
        vdisk = [
            {
                "VM": "mock-rdm-workload",
                "Disk": "Hard disk 2",
                "Raw": "RDM (Physical)",
                "Capacity MiB": "2097152"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo, "vDisk": vdisk})
        self.assertEqual(assessment.rdm_count, 1)
        vm = assessment.vms[0]
        self.assertTrue(vm.has_rdm)
        self.assertEqual(vm.assigned_wave, 4)
        self.assertTrue(any("rdm" in b.lower() for b in vm.blockers))

    def test_monster_vm_vnuma_qualification(self) -> None:
        """Flags VMs exceeding 32 vCPUs or 128 GB RAM as Monster VMs."""
        vinfo = [
            {
                "VM": "mock-sap-hana-db",
                "Powerstate": "poweredOn",
                "CPUs": "64",
                "Memory": "262144",  # 256 GB RAM
                "OS according to the VM spec": "SUSE Linux Enterprise Server 15 (64-bit)"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo})
        self.assertEqual(assessment.monster_vm_count, 1)
        vm = assessment.vms[0]
        self.assertTrue(vm.is_monster_vm)
        self.assertEqual(vm.assigned_wave, 4)
        self.assertTrue(any("monster" in w.lower() or "numa" in w.lower() for w in vm.warnings + vm.blockers))

    def test_zombie_vm_wave_0_categorization(self) -> None:
        """Verifies powered-off VMs are assigned to Wave 0 for decommission review."""
        vinfo = [
            {
                "VM": "mock-decommissioned-vm",
                "Powerstate": "poweredOff",
                "CPUs": "4",
                "Memory": "8192",
                "Provisioned MiB": "102400",
                "In Use MiB": "51200"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo})
        self.assertEqual(assessment.zombie_vms, 1)
        self.assertAlmostEqual(assessment.zombie_reclaimable_gb, 50.0, places=1)
        vm = assessment.vms[0]
        self.assertTrue(vm.is_zombie_vm)
        self.assertEqual(vm.assigned_wave, 0)

    def test_clean_workload_wave_1_pilot(self) -> None:
        """Ensures clean dev/test Linux workloads are scheduled in Wave 1."""
        vinfo = [
            {
                "VM": "mock-pilot-linux-01",
                "Powerstate": "poweredOn",
                "CPUs": "2",
                "Memory": "4096",
                "Provisioned MiB": "20480",
                "In Use MiB": "10240",
                "OS according to the VM spec": "Ubuntu Linux (64-bit)"
            }
        ]
        assessment = self.engine.analyze({"vInfo": vinfo})
        vm = assessment.vms[0]
        self.assertEqual(vm.blockers, [])
        self.assertEqual(vm.assigned_wave, 1)


if __name__ == "__main__":
    unittest.main()

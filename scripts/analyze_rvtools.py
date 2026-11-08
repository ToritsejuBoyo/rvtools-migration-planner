#!/usr/bin/env python3
"""
Script: analyze_rvtools.py
Skill:  rvtools-migration-planner (Day 10 / OP-13)
Purpose: Zero-dependency, read-only parser for VMware RVTools CSV exports
         (tabvInfo, tabvDisk, tabvSnapshot, tabvNetwork). Identifies migration
         blockers (RDMs, snapshots, multi-writer disks, vTPM/EFI, legacy OS)
         and calculates N+1 target cluster sizing for Proxmox VE or Hyper-V.
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def parse_float(val: Optional[str], default: float = 0.0) -> float:
    if not val:
        return default
    cleaned = str(val).strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_int(val: Optional[str], default: int = 0) -> int:
    return int(round(parse_float(val, float(default))))


def parse_bool(val: Optional[str]) -> bool:
    if not val:
        return False
    return str(val).strip().lower() in ("true", "1", "yes", "y")


def read_csv_normalized(path: Optional[str]) -> List[Dict[str, str]]:
    if not path or not os.path.isfile(path):
        return []
    rows: List[Dict[str, str]] = []
    with open(path, mode="r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            norm_row = {
                (k.strip() if k else ""): (v.strip() if v else "")
                for k, v in raw_row.items()
            }
            rows.append(norm_row)
    return rows


def get_col(row: Dict[str, str], candidates: List[str], default: str = "") -> str:
    lower_map = {k.lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return default


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze VMware RVTools CSV exports for Proxmox VE / Hyper-V migration planning."
    )
    parser.add_argument("--vinfo", required=True, help="Path to RVTools tabvInfo.csv")
    parser.add_argument("--vdisk", required=False, help="Path to RVTools tabvDisk.csv")
    parser.add_argument("--vsnapshot", required=False, help="Path to RVTools tabvSnapshot.csv")
    parser.add_argument("--vnetwork", required=False, help="Path to RVTools tabvNetwork.csv")
    parser.add_argument(
        "--target",
        choices=["proxmox", "hyperv"],
        default="proxmox",
        help="Target hypervisor platform (default: proxmox)",
    )
    parser.add_argument(
        "--vcpu-ratio",
        type=float,
        default=4.0,
        help="Target vCPU-to-pCore consolidation ratio (default: 4.0)",
    )
    parser.add_argument(
        "--host-cores",
        type=int,
        default=64,
        help="Physical CPU cores per target host node (default: 64)",
    )
    parser.add_argument(
        "--host-ram-gb",
        type=int,
        default=512,
        help="Physical RAM (GiB) per target host node (default: 512)",
    )
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Anonymize VM names, DNS names, and IP addresses in the output JSON",
    )
    parser.add_argument(
        "--output",
        default="./rvtools-assessment.json",
        help="Output JSON file path (default: ./rvtools-assessment.json)",
    )

    args = parser.parse_args()

    vinfo_rows = read_csv_normalized(args.vinfo)
    if not vinfo_rows:
        print(f"Error: No rows found or unable to read {args.vinfo}", file=sys.stderr)
        return 1

    vdisk_rows = read_csv_normalized(args.vdisk)
    vsnap_rows = read_csv_normalized(args.vsnapshot)
    vnet_rows = read_csv_normalized(args.vnetwork)

    # Index disks, snapshots, and networks by VM name
    rdm_by_vm: Dict[str, int] = {}
    shared_disk_by_vm: Dict[str, int] = {}
    for d in vdisk_rows:
        vm_name = get_col(d, ["VM", "VM Name"])
        is_raw = parse_bool(get_col(d, ["Raw", "RDM"]))
        sharing = get_col(d, ["Sharing", "Sharing mode"]).lower()
        if is_raw:
            rdm_by_vm[vm_name] = rdm_by_vm.get(vm_name, 0) + 1
        if "multi" in sharing or "shared" in sharing:
            shared_disk_by_vm[vm_name] = shared_disk_by_vm.get(vm_name, 0) + 1

    snap_by_vm: Dict[str, int] = {}
    for s in vsnap_rows:
        vm_name = get_col(s, ["VM", "VM Name"])
        if vm_name:
            snap_by_vm[vm_name] = snap_by_vm.get(vm_name, 0) + 1

    nic_by_vm: Dict[str, List[str]] = {}
    for n in vnet_rows:
        vm_name = get_col(n, ["VM", "VM Name"])
        adapter = get_col(n, ["Adapter", "Network Adapter", "NIC type"], "Unknown")
        if vm_name:
            nic_by_vm.setdefault(vm_name, []).append(adapter)

    total_vms = 0
    powered_on_vms = 0
    powered_off_vms = 0
    templates = 0

    active_vcpus = 0
    active_ram_mib = 0.0
    active_prov_mib = 0.0
    active_inuse_mib = 0.0

    readiness_counts = {"Green": 0, "Amber": 0, "Red": 0}
    os_distribution: Dict[str, int] = {}
    flagged_vms: List[Dict[str, Any]] = []

    for idx, row in enumerate(vinfo_rows, start=1):
        raw_vm_name = get_col(row, ["VM", "VM Name"], f"VM-{idx:04d}")
        vm_display = f"VM-{idx:04d}" if args.sanitize else raw_vm_name

        is_template = parse_bool(get_col(row, ["Template"]))
        if is_template:
            templates += 1
            continue

        total_vms += 1
        powerstate = get_col(row, ["Powerstate", "Power State"], "poweredOn").lower()
        is_on = "on" in powerstate

        cpus = parse_int(get_col(row, ["CPUs", "vCPU", "Num CPU"]), 1)
        mem_mib = parse_float(get_col(row, ["Memory", "Memory MB", "Memory MiB"]), 1024.0)
        prov_mib = parse_float(
            get_col(row, ["Provisioned MiB", "Provisioned MB", "Total disk capacity MiB"]),
            0.0,
        )
        inuse_mib = parse_float(get_col(row, ["In Use MiB", "In Use MB"]), prov_mib)
        firmware = get_col(row, ["Firmware", "BIOS/EFI"], "bios").lower()
        guest_os = get_col(
            row,
            [
                "OS according to the configuration file",
                "OS according to the VMware Tools",
                "Guest OS",
            ],
            "Unknown OS",
        )
        os_distribution[guest_os] = os_distribution.get(guest_os, 0) + 1

        if is_on:
            powered_on_vms += 1
            active_vcpus += cpus
            active_ram_mib += mem_mib
            active_prov_mib += prov_mib
            active_inuse_mib += inuse_mib
        else:
            powered_off_vms += 1

        # Evaluate migration blockers
        blockers: List[str] = []
        severity = "Green"

        rdm_count = rdm_by_vm.get(raw_vm_name, 0)
        shared_count = shared_disk_by_vm.get(raw_vm_name, 0)
        snap_count = snap_by_vm.get(raw_vm_name, parse_int(get_col(row, ["Snapshots"]), 0))
        nics = nic_by_vm.get(raw_vm_name, [])

        if rdm_count > 0:
            blockers.append(f"Raw Device Mapping (RDM) disks attached ({rdm_count})")
            severity = "Red"
        if shared_count > 0:
            blockers.append(f"Shared/Multi-Writer SCSI disks detected ({shared_count})")
            severity = "Red"
        if snap_count > 0:
            blockers.append(f"Active VMware snapshots must be consolidated ({snap_count})")
            if severity != "Red":
                severity = "Amber"
        if "efi" in firmware:
            blockers.append("UEFI firmware (verify Secure Boot / BitLocker / vTPM before cutover)")
            if severity != "Red":
                severity = "Amber"
        if "win" in guest_os.lower() and args.target == "proxmox":
            blockers.append("Windows Guest: Pre-stage signed VirtIO SCSI & NetKVM drivers")
            if severity != "Red":
                severity = "Amber"
        if any(legacy in guest_os.lower() for legacy in ("2003", "2008", "xp", "centos 6", "rhel 6")):
            blockers.append(f"Legacy/EOS Guest OS ({guest_os}): Limited modern VirtIO/VMBus support")
            severity = "Red"
        if cpus >= 16:
            blockers.append(f"Wide VM ({cpus} vCPUs): Configure NUMA topology alignment on target host")
            if severity == "Green":
                severity = "Amber"
        if any("e1000" in nic.lower() for nic in nics):
            blockers.append("Legacy E1000 NIC adapter detected; upgrade to VirtIO/VMBus post-migration")

        readiness_counts[severity] += 1
        if blockers:
            flagged_vms.append(
                {
                    "vm": vm_display,
                    "powerState": powerstate,
                    "vCPUs": cpus,
                    "memoryGiB": round(mem_mib / 1024.0, 2),
                    "provisionedGiB": round(prov_mib / 1024.0, 2),
                    "firmware": firmware.upper(),
                    "guestOS": guest_os,
                    "readiness": severity,
                    "findings": blockers,
                }
            )

    # Calculate Target Cluster Sizing (Active Workloads + N+1 HA)
    active_ram_gib = active_ram_mib / 1024.0
    active_prov_tib = active_prov_mib / (1024.0 * 1024.0)
    active_inuse_tib = active_inuse_mib / (1024.0 * 1024.0)

    required_pcores = math.ceil(active_vcpus / args.vcpu_ratio)
    # Account for 15% hypervisor + storage (Ceph/ZFS/S2D) RAM overhead and 80% max host load
    effective_host_ram_gib = args.host_ram_gb * 0.80
    ram_with_hypervisor_overhead_gib = active_ram_gib * 1.15

    nodes_by_cpu = max(1, math.ceil(required_pcores / (args.host_cores * 0.85)))
    nodes_by_ram = max(1, math.ceil(ram_with_hypervisor_overhead_gib / effective_host_ram_gib))
    active_nodes_needed = max(2, nodes_by_cpu, nodes_by_ram)
    total_nodes_n_plus_1 = active_nodes_needed + 1

    # Storage math: Ceph 3x replica + 25% safety buffer vs ZFS/SAN 2x mirror + 20% buffer
    ceph_raw_tib = round(active_prov_tib * 3.0 * 1.25, 2)
    mirror_raw_tib = round(active_prov_tib * 2.0 * 1.20, 2)

    report = {
        "schemaVersion": "1.0",
        "skill": "rvtools-migration-planner",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "targetPlatform": "Proxmox VE (KVM/QEMU)" if args.target == "proxmox" else "Microsoft Hyper-V",
        "sanitized": args.sanitize,
        "inventorySummary": {
            "totalVMsExcludingTemplates": total_vms,
            "poweredOnVMs": powered_on_vms,
            "poweredOffVMs": powered_off_vms,
            "templatesExcluded": templates,
            "activevCPUs": active_vcpus,
            "activeMemoryGiB": round(active_ram_gib, 2),
            "activeProvisionedTiB": round(active_prov_tib, 2),
            "activeConsumedTiB": round(active_inuse_tib, 2),
        },
        "migrationReadinessBreakdown": readiness_counts,
        "guestOSDistribution": os_distribution,
        "clusterSizingRecommendation": {
            "targetHostSpecAssumed": f"{args.host_cores} Physical Cores, {args.host_ram_gb} GiB RAM per host",
            "vCPUToPhysicalCoreRatio": f"{args.vcpu_ratio}:1",
            "requiredPhysicalCoresActive": required_pcores,
            "requiredRAMWithOverheadGiB": round(ram_with_hypervisor_overhead_gib, 2),
            "minimumActiveNodes": active_nodes_needed,
            "recommendedClusterNodesNPlus1": total_nodes_n_plus_1,
            "storageSizingTiB": {
                "usableRequiredProvisionedTiB": round(active_prov_tib, 2),
                "usableRequiredConsumedTiB": round(active_inuse_tib, 2),
                "ceph3ReplicaRawTiBWithBuffer": ceph_raw_tib,
                "zfsRaid10OrSanMirrorRawTiBWithBuffer": mirror_raw_tib,
            },
        },
        "flaggedWorkloads": flagged_vms[:150],
    }

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, mode="w", encoding="utf-8") as out_f:
        json.dump(report, out_f, indent=2)

    print(
        f"[+] RVTools assessment written to {args.output} "
        f"(Total VMs: {total_vms}, PoweredOn: {powered_on_vms}, Recommended N+1 Hosts: {total_nodes_n_plus_1})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

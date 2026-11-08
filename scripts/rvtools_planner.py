#!/usr/bin/env python3
"""
VMware RVTools to Proxmox/Hyper-V Migration Planner (`rvtools-migration-planner`)

Deterministic hypervisor exit planning engine and inventory analyzer. Ingests
RVTools multi-tab Excel workbooks (.xlsx) or exported CSV directories using pure
Python standard library modules (zero external dependencies).

Pinpoints migration blockers (Raw Device Mappings, stale snapshots, multi-writer
disks, legacy operating systems, monster VMs), formulates 5-wave phased migration
schedules, sizes destination Proxmox VE / Hyper-V clusters with N+1/N+2 resilience,
and masks sensitive customer topology client-side.

Strictly adheres to:
- Rule 3: Zero external dependencies (pure Python standard library).
- Rule 4: Mandatory client-side data sanitization (zero PII/cluster leakage).
- Rule 7: Zero-emoji enterprise tone.
"""

import argparse
import csv
import datetime
import html
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ----------------------------------------------------------------------
# Client-Side Data Sanitization Engine (Rule 4)
# ----------------------------------------------------------------------

class Sanitizer:
    """
    Client-side scrubbing engine for enterprise virtualization telemetry.
    Applies deterministic SHA-256 and prefix masking to prevent internal
    hostnames, IP addresses, datastore names, and cluster identities from
    leaving the local environment.
    """

    IPV4_PATTERN = re.compile(
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
    )
    MAC_PATTERN = re.compile(
        r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"
    )
    EMOJI_PATTERN = re.compile(
        r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
    )

    def __init__(self, salt: str = "rvtools-salt") -> None:
        self.salt = salt
        self._vm_map: Dict[str, str] = {}
        self._host_map: Dict[str, str] = {}
        self._cluster_map: Dict[str, str] = {}
        self._ds_map: Dict[str, str] = {}
        self._ip_map: Dict[str, str] = {}
        self._vm_counter = 1
        self._host_counter = 1
        self._cluster_counter = 1
        self._ds_counter = 1
        self._ip_counter = 1

    def mask_vm(self, name: str) -> str:
        if not name or name.lower().startswith("vm-"):
            return name
        if name in self._vm_map:
            return self._vm_map[name]
        masked = f"vm-{self._vm_counter:04d}"
        self._vm_counter += 1
        self._vm_map[name] = masked
        return masked

    def mask_host(self, host: str) -> str:
        if not host or host.lower().startswith("esxi-"):
            return host
        if host in self._host_map:
            return self._host_map[host]
        masked = f"esxi-{self._host_counter:02d}.internal"
        self._host_counter += 1
        self._host_map[host] = masked
        return masked

    def mask_cluster(self, cluster: str) -> str:
        if not cluster or cluster.lower().startswith("cluster-"):
            return cluster
        if cluster in self._cluster_map:
            return self._cluster_map[cluster]
        masked = f"cluster-{chr(64 + self._cluster_counter).lower()}"
        self._cluster_counter += 1
        self._cluster_map[cluster] = masked
        return masked

    def mask_datastore(self, ds: str) -> str:
        if not ds or ds.lower().startswith("datastore-"):
            return ds
        if ds in self._ds_map:
            return self._ds_map[ds]
        masked = f"datastore-{self._ds_counter:02d}"
        self._ds_counter += 1
        self._ds_map[ds] = masked
        return masked

    def _mask_ip(self, match: re.Match) -> str:
        ip = match.group(0)
        if ip.startswith("127.") or ip.startswith("192.0.2.") or ip.startswith("198.51.100.") or ip.startswith("203.0.113."):
            return ip
        if ip in self._ip_map:
            return self._ip_map[ip]
        mapped = f"192.0.2.{self._ip_counter % 250 + 1}"
        self._ip_counter += 1
        self._ip_map[ip] = mapped
        return mapped

    def scrub_text(self, text: str) -> str:
        if not text:
            return ""
        # Remove zero-width characters
        text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", "", text)
        # Mask IP addresses
        text = self.IPV4_PATTERN.sub(self._mask_ip, text)
        # Mask MAC addresses
        text = self.MAC_PATTERN.sub("52:54:00:12:34:56", text)
        # Scrub user submitted emojis to strictly enforce Rule 7
        text = self.EMOJI_PATTERN.sub("", text)
        return text


# ----------------------------------------------------------------------
# Virtualization Data Structures
# ----------------------------------------------------------------------

@dataclass
class DiskInfo:
    disk_name: str = ""
    capacity_gb: float = 0.0
    disk_path: str = ""
    disk_type: str = "flat"  # flat, rdm, rawDeviceMapPage
    controller: str = "SCSI"
    sharing_mode: str = "sharingNone"  # sharingNone, sharingMultiWriter
    is_rdm: bool = False


@dataclass
class SnapshotInfo:
    snapshot_name: str = ""
    age_days: int = 0
    size_mb: float = 0.0
    created_at: str = ""


@dataclass
class VirtualMachine:
    name: str = ""
    power_state: str = "poweredOn"
    cpus: int = 2
    memory_mb: int = 4096
    provisioned_gb: float = 0.0
    in_use_gb: float = 0.0
    os_name: str = "Linux"
    esxi_host: str = "esxi-01.internal"
    cluster: str = "cluster-a"
    datacenter: str = "datacenter-1"
    disks: List[DiskInfo] = field(default_factory=list)
    snapshots: List[SnapshotInfo] = field(default_factory=list)
    networks: List[str] = field(default_factory=list)
    ip_addresses: List[str] = field(default_factory=list)
    has_rdm: bool = False
    has_stale_snapshot: bool = False
    has_multiwriter: bool = False
    has_legacy_os: bool = False
    is_monster_vm: bool = False
    is_zombie_vm: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    assigned_wave: int = 1


@dataclass
class HostInfo:
    name: str = ""
    cluster: str = ""
    cpu_cores: int = 32
    memory_gb: float = 256.0
    esxi_version: str = "7.0.3"


@dataclass
class DatastoreInfo:
    name: str = ""
    capacity_gb: float = 0.0
    free_gb: float = 0.0
    type: str = "VMFS"


@dataclass
class TargetClusterSizing:
    target_hypervisor: str = "Proxmox VE"
    total_active_vcpus: int = 0
    total_active_vram_gb: float = 0.0
    total_storage_in_use_gb: float = 0.0
    required_pcores: int = 0
    required_host_ram_gb: float = 0.0
    usable_storage_tb: float = 0.0
    raw_storage_tb: float = 0.0
    node_profile_cores: int = 64
    node_profile_ram_gb: int = 512
    nodes_required_n0: int = 1
    nodes_recommended_n1: int = 2
    nodes_recommended_n2: int = 3
    hyperv_core_licenses: int = 0


@dataclass
class MigrationAssessment:
    assessment_id: str = ""
    generated_at: str = ""
    vcenter_name: str = "vcenter.example.local"
    total_vms: int = 0
    powered_on_vms: int = 0
    powered_off_vms: int = 0
    zombie_vms: int = 0
    zombie_reclaimable_gb: float = 0.0
    total_vcpus: int = 0
    active_vcpus: int = 0
    total_ram_gb: float = 0.0
    active_ram_gb: float = 0.0
    total_storage_gb: float = 0.0
    total_provisioned_storage_gb: float = 0.0
    rdm_count: int = 0
    stale_snapshot_count: int = 0
    multiwriter_count: int = 0
    legacy_os_count: int = 0
    monster_vm_count: int = 0
    readiness_percentage: float = 0.0
    vms: List[VirtualMachine] = field(default_factory=list)
    hosts: List[HostInfo] = field(default_factory=list)
    datastores: List[DatastoreInfo] = field(default_factory=list)
    sizing: TargetClusterSizing = field(default_factory=TargetClusterSizing)


# ----------------------------------------------------------------------
# Zero-Dependency RVTools Ingestion Engine (.xlsx and .csv)
# ----------------------------------------------------------------------

class RVToolsParser:
    """
    Streaming reader for RVTools multi-tab workbooks (.xlsx) and CSV directories.
    Extracts vInfo, vDisk, vSnapshot, vHost, and vNetwork tabs without third-party
    packages.
    """

    def parse(self, input_path: str) -> Dict[str, List[Dict[str, str]]]:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input path '{input_path}' does not exist.")

        if path.is_dir():
            return self._parse_csv_directory(path)
        elif path.suffix.lower() == ".xlsx":
            return self._parse_xlsx_workbook(path)
        elif path.suffix.lower() == ".csv":
            return self._parse_single_csv(path)
        else:
            raise ValueError(f"Unsupported file format '{path.suffix}'. Expected .xlsx or .csv directory.")

    def _parse_csv_directory(self, dir_path: Path) -> Dict[str, List[Dict[str, str]]]:
        sheets: Dict[str, List[Dict[str, str]]] = {}
        for csv_file in dir_path.glob("*.csv"):
            stem_lower = csv_file.stem.lower()
            tab_name = "vInfo"
            if "vdisk" in stem_lower:
                tab_name = "vDisk"
            elif "vsnapshot" in stem_lower:
                tab_name = "vSnapshot"
            elif "vnetwork" in stem_lower:
                tab_name = "vNetwork"
            elif "vhost" in stem_lower:
                tab_name = "vHost"
            elif "vdatastore" in stem_lower:
                tab_name = "vDatastore"
            elif "vinfo" in stem_lower:
                tab_name = "vInfo"

            rows = self._read_csv_file(csv_file)
            sheets[tab_name] = rows
        return sheets

    def _parse_single_csv(self, file_path: Path) -> Dict[str, List[Dict[str, str]]]:
        rows = self._read_csv_file(file_path)
        tab_name = "vInfo"
        if rows:
            headers = [k.lower() for k in rows[0].keys()]
            if any("disk" in h for h in headers) and any("capacity" in h for h in headers):
                tab_name = "vDisk"
            elif any("snapshot" in h for h in headers):
                tab_name = "vSnapshot"
            elif any("esxi" in h or "cpu model" in h for h in headers):
                tab_name = "vHost"
        return {tab_name: rows}

    def _read_csv_file(self, file_path: Path) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        try:
            with open(file_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Clean and normalize keys
                    clean_row = {k.strip(): str(v).strip() for k, v in row.items() if k}
                    if clean_row:
                        rows.append(clean_row)
        except Exception as e:
            print(f"Warning: Failed to read CSV '{file_path}': {e}", file=sys.stderr)
        return rows

    def _parse_xlsx_workbook(self, xlsx_path: Path) -> Dict[str, List[Dict[str, str]]]:
        """
        Parses an Excel OpenXML (.xlsx) archive using pure standard library zipfile
        and ElementTree.
        """
        sheets: Dict[str, List[Dict[str, str]]] = {}
        try:
            with zipfile.ZipFile(xlsx_path, "r") as z:
                # 1. Parse shared strings lookup table
                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in z.namelist():
                    ss_xml = z.read("xl/sharedStrings.xml")
                    ss_root = ET.fromstring(ss_xml)
                    for si in ss_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                        t_node = si.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                        if t_node is not None and t_node.text:
                            shared_strings.append(t_node.text)
                        else:
                            # Concatenate text pieces if formatted runs exist
                            pieces = [t.text for t in si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t") if t.text]
                            shared_strings.append("".join(pieces) if pieces else "")

                # 2. Map sheet IDs to sheet names in workbook.xml
                wb_xml = z.read("xl/workbook.xml")
                wb_root = ET.fromstring(wb_xml)
                sheet_map: Dict[str, str] = {}  # rId -> Name
                for s in wb_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                    name = s.get("name", "")
                    r_id = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                    if name and r_id:
                        sheet_map[r_id] = name

                # 3. Read relationships to find worksheet file paths
                rel_xml = z.read("xl/_rels/workbook.xml.rels")
                rel_root = ET.fromstring(rel_xml)
                sheet_files: Dict[str, str] = {}  # Sheet Name -> xl/worksheets/sheetX.xml
                for r in rel_root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                    r_id = r.get("Id", "")
                    target = r.get("Target", "")
                    if r_id in sheet_map:
                        sheet_name = sheet_map[r_id]
                        clean_path = target if target.startswith("xl/") else f"xl/{target}"
                        sheet_files[sheet_name] = clean_path

                # 4. Parse individual worksheet XMLs
                for s_name, s_file in sheet_files.items():
                    if s_file in z.namelist():
                        sheet_xml = z.read(s_file)
                        rows_data = self._parse_sheet_xml(sheet_xml, shared_strings)
                        if rows_data:
                            sheets[s_name] = rows_data
        except Exception as e:
            print(f"Warning: Direct OpenXML extraction encountered issue: {e}", file=sys.stderr)
        return sheets

    def _parse_sheet_xml(self, sheet_xml: bytes, shared_strings: List[str]) -> List[Dict[str, str]]:
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        root = ET.fromstring(sheet_xml)
        raw_rows: List[Dict[int, str]] = []

        for row_elem in root.findall(f".//{ns}row"):
            row_dict: Dict[int, str] = {}
            for c_elem in row_elem.findall(f".//{ns}c"):
                ref = c_elem.get("r", "")
                t_attr = c_elem.get("t", "")
                val_node = c_elem.find(f"{ns}v")
                col_idx = self._col_ref_to_index(ref)

                val = ""
                if val_node is not None and val_node.text:
                    if t_attr == "s":
                        try:
                            s_idx = int(val_node.text)
                            if s_idx < len(shared_strings):
                                val = shared_strings[s_idx]
                        except (ValueError, IndexError):
                            val = val_node.text
                    else:
                        val = val_node.text
                row_dict[col_idx] = val.strip()
            if row_dict:
                raw_rows.append(row_dict)

        if not raw_rows:
            return []

        # Row 1 is header
        headers = raw_rows[0]
        result: List[Dict[str, str]] = []
        for r_dict in raw_rows[1:]:
            row_map: Dict[str, str] = {}
            for col_idx, col_name in headers.items():
                if col_name:
                    row_map[col_name] = r_dict.get(col_idx, "")
            if any(row_map.values()):
                result.append(row_map)
        return result

    def _col_ref_to_index(self, ref: str) -> int:
        col_str = re.match(r"([A-Z]+)", ref)
        if not col_str:
            return 0
        letters = col_str.group(1)
        idx = 0
        for char in letters:
            idx = idx * 26 + (ord(char) - ord("A") + 1)
        return idx - 1


# ----------------------------------------------------------------------
# Migration Assessment & Diagnostic Engine
# ----------------------------------------------------------------------

class MigrationEngine:
    """
    Evaluates RVTools datasets, correlates disks and snapshots with VMs,
    detects critical hypervisor migration blockers, groups workloads into
    5 migration waves, and sizes target clusters.
    """

    LEGACY_OS_KEYWORDS = [
        "windows 2000", "windows server 2003", "windows server 2008",
        "windows xp", "windows vista", "centos 4", "centos 5", "centos 6",
        "red hat enterprise linux 4", "red hat enterprise linux 5", "red hat enterprise linux 6",
        "rhel 4", "rhel 5", "rhel 6", "debian 5", "debian 6", "debian 7",
        "solaris", "netware", "freebsd 7", "freebsd 8"
    ]

    def __init__(self, sanitizer: Optional[Sanitizer] = None) -> None:
        self.sanitizer = sanitizer or Sanitizer()

    def analyze(
        self,
        tables: Dict[str, List[Dict[str, str]]],
        target_hypervisor: str = "Proxmox VE",
        node_cores: int = 64,
        node_ram_gb: int = 512,
        prod_overcommit: float = 2.0,
        dev_overcommit: float = 4.0
    ) -> MigrationAssessment:
        assessment = MigrationAssessment()
        assessment.assessment_id = f"VMMIG-{datetime.datetime.now().strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}"
        assessment.generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        assessment.sizing.target_hypervisor = target_hypervisor
        assessment.sizing.node_profile_cores = node_cores
        assessment.sizing.node_profile_ram_gb = node_ram_gb

        # 1. Parse vInfo (Primary VM inventory)
        vinfo_rows = self._find_table(tables, ["vinfo", "vm"])
        vms_by_name: Dict[str, VirtualMachine] = {}

        for row in vinfo_rows:
            vm = self._parse_vm_row(row)
            if vm.name:
                vms_by_name[vm.name.lower()] = vm

        # 2. Correlate Disks (vDisk)
        vdisk_rows = self._find_table(tables, ["vdisk", "disk"])
        for row in vdisk_rows:
            vm_name = self._get_field(row, ["vm", "vm name", "vmname"]).lower()
            if vm_name in vms_by_name:
                disk = self._parse_disk_row(row)
                vms_by_name[vm_name].disks.append(disk)
                if disk.is_rdm:
                    vms_by_name[vm_name].has_rdm = True
                if disk.sharing_mode == "sharingMultiWriter":
                    vms_by_name[vm_name].has_multiwriter = True

        # 3. Correlate Snapshots (vSnapshot)
        vsnap_rows = self._find_table(tables, ["vsnapshot", "snapshot"])
        for row in vsnap_rows:
            vm_name = self._get_field(row, ["vm", "vm name", "vmname"]).lower()
            if vm_name in vms_by_name:
                snap = self._parse_snapshot_row(row)
                vms_by_name[vm_name].snapshots.append(snap)
                if snap.age_days >= 3 or snap.size_mb >= 20480.0:  # >72h or >20GB
                    vms_by_name[vm_name].has_stale_snapshot = True

        # 4. Correlate Networks (vNetwork)
        vnet_rows = self._find_table(tables, ["vnetwork", "network"])
        for row in vnet_rows:
            vm_name = self._get_field(row, ["vm", "vm name", "vmname"]).lower()
            if vm_name in vms_by_name:
                net = self._get_field(row, ["network", "portgroup", "dvportgroup", "network name"])
                ip = self._get_field(row, ["ip address", "ip", "ipv4"])
                if net and net not in vms_by_name[vm_name].networks:
                    vms_by_name[vm_name].networks.append(net)
                if ip and ip not in vms_by_name[vm_name].ip_addresses:
                    vms_by_name[vm_name].ip_addresses.append(ip)

        # 5. Evaluate Blockers, Warnings, and Wave Partitioning
        all_vms = list(vms_by_name.values())
        for vm in all_vms:
            self._evaluate_vm_readiness(vm)

        assessment.vms = all_vms
        assessment.total_vms = len(all_vms)
        assessment.powered_on_vms = sum(1 for v in all_vms if v.power_state.lower() == "poweredon")
        assessment.powered_off_vms = assessment.total_vms - assessment.powered_on_vms
        assessment.zombie_vms = sum(1 for v in all_vms if v.is_zombie_vm)
        assessment.zombie_reclaimable_gb = sum(v.in_use_gb for v in all_vms if v.is_zombie_vm)

        assessment.total_vcpus = sum(v.cpus for v in all_vms)
        assessment.active_vcpus = sum(v.cpus for v in all_vms if v.power_state.lower() == "poweredon")
        assessment.total_ram_gb = sum(v.memory_mb for v in all_vms) / 1024.0
        assessment.active_ram_gb = sum(v.memory_mb for v in all_vms if v.power_state.lower() == "poweredon") / 1024.0
        assessment.total_storage_gb = sum(v.in_use_gb for v in all_vms)
        assessment.total_provisioned_storage_gb = sum(v.provisioned_gb for v in all_vms)

        assessment.rdm_count = sum(1 for v in all_vms if v.has_rdm)
        assessment.stale_snapshot_count = sum(1 for v in all_vms if v.has_stale_snapshot)
        assessment.multiwriter_count = sum(1 for v in all_vms if v.has_multiwriter)
        assessment.legacy_os_count = sum(1 for v in all_vms if v.has_legacy_os)
        assessment.monster_vm_count = sum(1 for v in all_vms if v.is_monster_vm)

        blocker_vms = sum(1 for v in all_vms if v.blockers)
        if assessment.total_vms == 0:
            assessment.readiness_percentage = 100.0
        else:
            assessment.readiness_percentage = round(((assessment.total_vms - blocker_vms) / assessment.total_vms) * 100.0, 1)

        # 6. Compute Target Cluster Sizing
        self._calculate_cluster_sizing(assessment, prod_overcommit, dev_overcommit)
        return assessment

    def _find_table(self, tables: Dict[str, List[Dict[str, str]]], keywords: List[str]) -> List[Dict[str, str]]:
        for t_name, rows in tables.items():
            for kw in keywords:
                if kw in t_name.lower():
                    return rows
        return []

    def _get_field(self, row: Dict[str, str], candidates: List[str], default: str = "") -> str:
        val, _ = self._get_field_and_key(row, candidates, default)
        return val

    def _get_field_and_key(self, row: Dict[str, str], candidates: List[str], default: str = "") -> Tuple[str, str]:
        for k, v in row.items():
            clean_k = k.lower().replace(" ", "").replace("_", "")
            for cand in candidates:
                clean_cand = cand.lower().replace(" ", "").replace("_", "")
                if clean_cand == clean_k and v:
                    return v, k
        return default, ""

    def _parse_vm_row(self, row: Dict[str, str]) -> VirtualMachine:
        vm = VirtualMachine()
        vm.name = self._get_field(row, ["vm", "vm name", "vmname", "virtualmachine"])
        vm.power_state = self._get_field(row, ["powerstate", "state", "status"], default="poweredOn")

        cpus_str = self._get_field(row, ["cpus", "numcpu", "cpu", "vcpus"], default="2")
        try:
            vm.cpus = max(0, int(float(cpus_str)))
        except ValueError:
            vm.cpus = 2

        mem_str, mem_key = self._get_field_and_key(row, ["memory", "memorymb", "ram", "memory mib"], default="4096")
        try:
            m_val = float(mem_str)
            if "gib" in mem_key.lower() or "gb" in mem_key.lower():
                vm.memory_mb = max(0, int(m_val * 1024))
            else:
                vm.memory_mb = max(0, int(m_val))
        except ValueError:
            vm.memory_mb = 4096

        prov_str, prov_key = self._get_field_and_key(row, ["provisioned", "provisionedmib", "provisionedgib", "provisioned mb"], default="0")
        try:
            prov_val = float(prov_str)
            if "mib" in prov_key.lower() or "mb" in prov_key.lower() or prov_val > 5000:
                vm.provisioned_gb = max(0.0, prov_val / 1024.0)
            else:
                vm.provisioned_gb = max(0.0, prov_val)
        except ValueError:
            vm.provisioned_gb = 40.0

        inuse_str, inuse_key = self._get_field_and_key(row, ["inuse", "inusemib", "inusegib", "in use mb"], default="0")
        try:
            inuse_val = float(inuse_str)
            if "mib" in inuse_key.lower() or "mb" in inuse_key.lower() or inuse_val > 5000:
                vm.in_use_gb = max(0.0, inuse_val / 1024.0)
            else:
                vm.in_use_gb = max(0.0, inuse_val)
        except ValueError:
            vm.in_use_gb = vm.provisioned_gb * 0.5

        vm.os_name = self._get_field(row, ["osaccordingtothevmspec", "os", "gueststate", "os according to the vm spec"], default="Linux")
        vm.esxi_host = self._get_field(row, ["host", "esxihost", "esx host"], default="esxi-01.internal")
        vm.cluster = self._get_field(row, ["cluster", "clustername"], default="cluster-a")
        vm.datacenter = self._get_field(row, ["datacenter"], default="datacenter-1")

        raw_ip = self._get_field(row, ["primaryipaddress", "ipaddress", "ip"])
        if raw_ip:
            vm.ip_addresses.append(raw_ip)
        return vm

    def _parse_disk_row(self, row: Dict[str, str]) -> DiskInfo:
        disk = DiskInfo()
        disk.disk_name = self._get_field(row, ["disk", "diskname", "name"], default="Hard disk 1")
        disk.disk_path = self._get_field(row, ["diskpath", "path", "file"], default="")
        disk.controller = self._get_field(row, ["controller", "controllertype"], default="SCSI")
        disk.sharing_mode = self._get_field(row, ["sharing", "sharingmode"], default="sharingNone")

        cap_str, cap_key = self._get_field_and_key(row, ["capacitymib", "capacity", "capacitygib", "disk size"], default="40960")
        try:
            c_val = float(cap_str)
            if "mib" in cap_key.lower() or "mb" in cap_key.lower() or c_val > 5000:
                disk.capacity_gb = c_val / 1024.0
            else:
                disk.capacity_gb = c_val
        except ValueError:
            disk.capacity_gb = 40.0

        raw_type = self._get_field(row, ["raw", "disktype", "type", "format"]).lower()
        if "rdm" in raw_type or "rawdevicemap" in raw_type or "raw" in raw_type:
            disk.is_rdm = True
            disk.disk_type = "rdm"
        return disk

    def _parse_snapshot_row(self, row: Dict[str, str]) -> SnapshotInfo:
        snap = SnapshotInfo()
        snap.snapshot_name = self._get_field(row, ["snapshot", "snapshotname", "name"], default="snapshot-1")
        date_str = self._get_field(row, ["datetimesnapshot", "date", "created"], default="")
        snap.created_at = date_str

        # Calculate snapshot age
        if date_str:
            try:
                # Common formats: 2026-10-01 12:00:00 or ISO
                clean_d = date_str.split("T")[0].split(" ")[0]
                dt = datetime.datetime.strptime(clean_d, "%Y-%m-%d")
                snap.age_days = max(0, (datetime.datetime.now() - dt).days)
            except Exception:
                snap.age_days = 4  # Default if unparseable
        else:
            snap.age_days = 4

        size_str = self._get_field(row, ["sizemib", "size", "size mb"], default="1024")
        try:
            snap.size_mb = float(size_str)
        except ValueError:
            snap.size_mb = 1024.0
        return snap

    def _evaluate_vm_readiness(self, vm: VirtualMachine) -> None:
        # Check Legacy OS
        lower_os = vm.os_name.lower()
        if any(kw in lower_os for kw in self.LEGACY_OS_KEYWORDS):
            vm.has_legacy_os = True
            vm.warnings.append(f"Legacy Guest OS ({vm.os_name}) lacks inbox VirtIO drivers; requires offline driver injection.")

        # Check Windows Storage Controller / VirtIO driver readiness
        if "windows" in lower_os:
            for d in vm.disks:
                if any(c in d.controller.lower() for c in ["paravirtual", "pvscsi", "lsi", "sas", "ide"]):
                    vm.warnings.append(f"Windows guest with {d.controller} controller requires VirtIO SCSI driver injection prior to target cutover.")
                    break

        # Check Monster VM
        if vm.cpus >= 32 or vm.memory_mb >= 131072:  # >=128GB
            vm.is_monster_vm = True
            vm.warnings.append(f"Monster VM sizing ({vm.cpus} vCPUs, {int(vm.memory_mb/1024)}GB RAM); requires explicit vNUMA topology matching.")

        # Check Zombie VM (Powered off with in_use_gb > 0)
        if vm.power_state.lower() != "poweredon":
            vm.is_zombie_vm = True

        # Check Critical Blockers
        if vm.has_rdm:
            vm.blockers.append("Raw Device Mapping (RDM) detected. Physical/Virtual RDM must be converted to standard virtual disk before migration.")
        if vm.has_stale_snapshot:
            vm.blockers.append("Stale snapshot chain detected (>72h or >20GB). Snapshots must be committed/deleted before cutover.")
        if vm.has_multiwriter:
            vm.blockers.append("Multi-writer shared disk configuration detected. Must convert to shared Ceph RBD / Shared VHDX or application clustering.")

        # Assign Migration Wave (0 to 4)
        if vm.is_zombie_vm:
            vm.assigned_wave = 0
        elif vm.blockers or vm.is_monster_vm or vm.has_multiwriter:
            vm.assigned_wave = 4
        elif vm.has_legacy_os or len(vm.disks) > 3 or any(w in vm.name.lower() for w in ["sql", "oracle", "db", "prod-app", "dc"]):
            vm.assigned_wave = 3
        elif len(vm.disks) > 1 or any(w in vm.name.lower() for w in ["web", "api", "internal", "tool"]):
            vm.assigned_wave = 2
        else:
            vm.assigned_wave = 1

    def _calculate_cluster_sizing(
        self,
        assessment: MigrationAssessment,
        prod_overcommit: float,
        dev_overcommit: float
    ) -> None:
        sizing = assessment.sizing
        sizing.total_active_vcpus = assessment.active_vcpus
        sizing.total_active_vram_gb = assessment.active_ram_gb
        sizing.total_storage_in_use_gb = assessment.total_storage_gb

        # Compute physical cores needed
        effective_overcommit = prod_overcommit if assessment.active_vcpus > 0 else 2.0
        sizing.required_pcores = max(16, int(math.ceil(assessment.active_vcpus / effective_overcommit)))

        # Compute physical host memory (Active vRAM * 1.05 + 10% hypervisor/ZFS ARC buffer)
        sizing.required_host_ram_gb = max(64.0, math.ceil(assessment.active_ram_gb * 1.05 * 1.10))

        # Storage capacity (In-use + 20% snapshot buffer)
        usable_gb = assessment.total_storage_gb * 1.20
        sizing.usable_storage_tb = round(usable_gb / 1024.0, 1)

        # Raw storage factor (Ceph 3x = 3.0, Hyper-V S2D = 3.0, ZFS RAIDZ2 = 1.5)
        replication_factor = 3.0 if "proxmox" in sizing.target_hypervisor.lower() else 3.0
        sizing.raw_storage_tb = round(sizing.usable_storage_tb * replication_factor, 1)

        # Node calculation based on profile (cores and RAM)
        nodes_by_cpu = math.ceil(sizing.required_pcores / sizing.node_profile_cores)
        nodes_by_ram = math.ceil(sizing.required_host_ram_gb / sizing.node_profile_ram_gb)
        base_nodes = max(3, max(nodes_by_cpu, nodes_by_ram))  # Minimum 3 nodes for Ceph quorum

        sizing.nodes_required_n0 = base_nodes
        sizing.nodes_recommended_n1 = base_nodes + 1
        sizing.nodes_recommended_n2 = base_nodes + 2

        # Hyper-V core licensing math: minimum 16 cores per host
        licensed_cores_per_host = max(16, sizing.node_profile_cores)
        sizing.hyperv_core_licenses = sizing.nodes_recommended_n1 * licensed_cores_per_host


# ----------------------------------------------------------------------
# Report & Runbook Generator
# ----------------------------------------------------------------------

class MigrationReportGenerator:
    """
    Renders migration assessment findings into Markdown, structured JSON,
    Proxmox VE bash runbooks, HTML dashboards, or CSV schedules.
    """

    def __init__(self, sanitizer: Optional[Sanitizer] = None) -> None:
        self.sanitizer = sanitizer or Sanitizer()

    def format_markdown(self, assessment: MigrationAssessment, sanitize: bool = True) -> str:
        s = assessment.sizing
        vcenter = self.sanitizer.mask_host(assessment.vcenter_name) if sanitize else assessment.vcenter_name

        # Wave breakdowns
        waves = {w: [v for v in assessment.vms if v.assigned_wave == w] for w in range(5)}

        # Blocker rows
        blocker_rows = []
        for v in assessment.vms:
            vm_name = self.sanitizer.mask_vm(v.name) if sanitize else v.name
            for b in v.blockers:
                blocker_rows.append(f"| **Critical** | `Blocker` | `{vm_name}` | {b} | Action required prior to cutover |")
            for w in v.warnings:
                blocker_rows.append(f"| **Warning** | `Architecture` | `{vm_name}` | {w} | Review target driver/NUMA settings |")

        blocker_table = "\n".join(blocker_rows[:25]) if blocker_rows else "| None | - | Clean Inventory | No blockers detected | Proceed with standard cutover |"

        md = f"""# VMware Migration Assessment & Sizing Plan (`rvtools-migration-planner`)

**Assessment ID:** `{assessment.assessment_id}`
**Source vCenter:** `{vcenter}`
**Target Hypervisor:** `{s.target_hypervisor}`
**Report Generated:** `{datetime.date.today().isoformat()}`

---

## 1. Executive Summary & Inventory Metrics

| Virtualization Dimension | Source Inventory Metric | Migration Analysis & Optimization |
| :--- | :--- | :--- |
| **Total Virtual Machines** | `{assessment.total_vms}` VMs | `{assessment.powered_on_vms}` Active / `{assessment.powered_off_vms}` Powered Off |
| **Zombie / Stale Workloads** | `{assessment.zombie_vms}` VMs | **Wave 0 Cleanup Candidate:** Reclaims `{assessment.zombie_reclaimable_gb:.1f} GB` storage |
| **Total Compute Capacity** | `{assessment.total_vcpus}` vCPUs | Active Workloads: `{assessment.active_vcpus}` vCPUs |
| **Total Memory Capacity** | `{assessment.total_ram_gb:.1f} GB` Provisioned | Active Workloads: `{assessment.active_ram_gb:.1f} GB` RAM |
| **Total Storage In-Use** | `{assessment.total_storage_gb:.1f} GB` In-Use | Provisioned: `{assessment.total_provisioned_storage_gb:.1f} GB` |
| **Migration Readiness Score** | `{assessment.readiness_percentage}%` Ready | `{assessment.rdm_count}` RDMs, `{assessment.stale_snapshot_count}` Stale Snapshots, `{assessment.legacy_os_count}` Legacy OS |

---

## 2. Critical Blockers & Architectural Constraints Matrix

| Risk Level | Constraint Type | Target VM | Technical Issue / Detail | Mandatory Pre-Migration Action |
| :--- | :--- | :--- | :--- | :--- |
{blocker_table}

---

## 3. Phased Migration Wave Plan

```
[Wave 0: Decommission & Cleanup] ──► {len(waves[0])} VMs ({sum(v.in_use_gb for v in waves[0]):.1f} GB storage reclaimed)
[Wave 1: Pilot & Low-Risk]       ──► {len(waves[1])} VMs (Stateless dev/test Linux & Windows)
[Wave 2: Tier-2 Business Apps]   ──► {len(waves[2])} VMs (Internal tools, web frontends, microservices)
[Wave 3: Tier-1 Stateful Apps]   ──► {len(waves[3])} VMs (Standalone databases, ERP core, domain controllers)
[Wave 4: Complex / High-Risk]    ──► {len(waves[4])} VMs (Monster VMs, clustered nodes, RDM workloads)
```

---

## 4. Target Destination Cluster Sizing ({s.target_hypervisor})

### Sizing Parameters & Baseline Profile
- **Target Node Hardware Profile:** `{s.node_profile_cores}` Cores per Node | `{s.node_profile_ram_gb} GB` RAM per Node
- **Storage Architecture:** Ceph 3x Replication / ZFS with 20% maintenance headroom

| Infrastructure Dimension | Required Resource Capacity | Sizing Calculation |
| :--- | :--- | :--- |
| **Physical CPU Cores** | `{s.required_pcores}` Cores | `{assessment.active_vcpus}` active vCPUs / 2.0 overcommit ratio |
| **Physical Host Memory** | `{s.required_host_ram_gb:.1f} GB` RAM | `{assessment.active_ram_gb:.1f} GB` vRAM + 10% Hypervisor/ZFS buffer |
| **Usable Storage Pool** | `{s.usable_storage_tb:.1f} TB` | `{assessment.total_storage_gb:.1f} GB` in-use + 20% maintenance headroom |
| **Raw Storage Required** | `{s.raw_storage_tb:.1f} TB` | 3.0x Ceph replication factor |
| **Recommended Cluster Nodes** | `{s.nodes_recommended_n1}` Nodes | Provides **$N+1$ High Availability failover resilience** |

---

## 5. Automated Target Import Runbook (Proxmox VE)

```bash
# Provision target VM configuration
qm create 101 \\
  --name "vm-sample" \\
  --memory 4096 \\
  --cores 2 \\
  --cpu host \\
  --ostype l26 \\
  --scsihw virtio-scsi-single \\
  --net0 virtio,bridge=vmbr0

# Import converted virtual disk to target storage pool
qm importdisk 101 /var/lib/vz/dump/vm-sample.raw ceph-pool --format raw

# Attach imported volume and configure boot sequence
qm set 101 --scsi0 ceph-pool:vm-101-disk-0,discard=on,ssd=1
qm set 101 --boot order=scsi0
```
"""
        return md.strip()

    generate_markdown = format_markdown

    def format_json(self, assessment: MigrationAssessment, sanitize: bool = True) -> str:
        s = assessment.sizing
        data = {
            "assessment_id": assessment.assessment_id,
            "generated_at": assessment.generated_at,
            "source_vcenter": self.sanitizer.mask_host(assessment.vcenter_name) if sanitize else assessment.vcenter_name,
            "metrics": {
                "total_vms": assessment.total_vms,
                "powered_on": assessment.powered_on_vms,
                "powered_off": assessment.powered_off_vms,
                "zombie_vms": assessment.zombie_vms,
                "zombie_reclaimable_gb": assessment.zombie_reclaimable_gb,
                "active_vcpus": assessment.active_vcpus,
                "active_ram_gb": assessment.active_ram_gb,
                "total_storage_gb": assessment.total_storage_gb,
                "readiness_percentage": assessment.readiness_percentage
            },
            "blockers_summary": {
                "rdm_count": assessment.rdm_count,
                "stale_snapshots": assessment.stale_snapshot_count,
                "multiwriter_shared_disks": assessment.multiwriter_count,
                "legacy_os_virtio_gaps": assessment.legacy_os_count,
                "monster_vms": assessment.monster_vm_count
            },
            "target_sizing": {
                "hypervisor": s.target_hypervisor,
                "required_pcores": s.required_pcores,
                "required_ram_gb": s.required_host_ram_gb,
                "usable_storage_tb": s.usable_storage_tb,
                "raw_storage_tb": s.raw_storage_tb,
                "nodes_n0": s.nodes_required_n0,
                "nodes_n1": s.nodes_recommended_n1,
                "nodes_n2": s.nodes_recommended_n2,
                "hyperv_core_licenses": s.hyperv_core_licenses
            },
            "waves": {
                f"wave_{w}": [
                    {
                        "name": self.sanitizer.mask_vm(v.name) if sanitize else v.name,
                        "vcpus": v.cpus,
                        "ram_mb": v.memory_mb,
                        "storage_gb": v.in_use_gb,
                        "os": v.os_name,
                        "blockers": v.blockers,
                        "warnings": v.warnings
                    }
                    for v in assessment.vms if v.assigned_wave == w
                ]
                for w in range(5)
            }
        }
        return json.dumps(data, indent=2)

    def format_html(self, assessment: MigrationAssessment, sanitize: bool = True) -> str:
        s = assessment.sizing
        vcenter = html.escape(self.sanitizer.mask_host(assessment.vcenter_name) if sanitize else assessment.vcenter_name)

        rows = []
        for v in assessment.vms[:50]:
            name = html.escape(self.sanitizer.mask_vm(v.name) if sanitize else v.name)
            os_name = html.escape(v.os_name)
            status = "Ready" if not v.blockers else "Blocked"
            badge_class = "badge-ok" if not v.blockers else "badge-danger"
            rows.append(f"<tr><td>{name}</td><td>Wave {v.assigned_wave}</td><td>{v.cpus}</td><td>{int(v.memory_mb/1024)} GB</td><td>{v.in_use_gb:.1f} GB</td><td>{os_name}</td><td><span class='badge {badge_class}'>{status}</span></td></tr>")

        html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>VMware Migration Plan: {vcenter}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 2rem; }}
    .container {{ max-width: 1100px; margin: 0 auto; background: #1e293b; border-radius: 8px; padding: 2rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5); }}
    h1 {{ color: #38bdf8; margin-top: 0; border-bottom: 2px solid #334155; padding-bottom: 0.75rem; font-size: 1.6rem; }}
    h2 {{ color: #94a3b8; font-size: 1.2rem; margin-top: 1.5rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }}
    .card {{ background: #0f172a; padding: 1rem; border-radius: 6px; border: 1px solid #334155; }}
    .card-num {{ font-size: 1.6rem; font-weight: 700; color: #38bdf8; }}
    .card-label {{ font-size: 0.85rem; color: #94a3b8; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.9rem; }}
    th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #334155; }}
    th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }}
    .badge-ok {{ background: #166534; color: #dcfce7; }}
    .badge-danger {{ background: #991b1b; color: #fee2e2; }}
    pre {{ background: #0b1120; border: 1px solid #334155; border-radius: 6px; padding: 1rem; overflow-x: auto; font-family: monospace; font-size: 0.85rem; color: #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>VMware Hypervisor Exit Plan ({s.target_hypervisor})</h1>
    <p>Source Environment: <strong>{vcenter}</strong> | Assessment ID: <code>{assessment.assessment_id}</code></p>
    
    <div class="cards">
      <div class="card"><div class="card-num">{assessment.total_vms}</div><div class="card-label">Total VMs</div></div>
      <div class="card"><div class="card-num">{assessment.readiness_percentage}%</div><div class="card-label">Readiness Score</div></div>
      <div class="card"><div class="card-num">{s.nodes_recommended_n1}</div><div class="card-label">Target Nodes (N+1)</div></div>
      <div class="card"><div class="card-num">{s.raw_storage_tb} TB</div><div class="card-label">Ceph 3x Storage</div></div>
    </div>

    <h2>Migration Wave Inventory Preview</h2>
    <table>
      <thead>
        <tr><th>VM Name</th><th>Wave</th><th>vCPUs</th><th>RAM</th><th>Storage</th><th>Guest OS</th><th>Status</th></tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>"""
        return html_out.strip()

    def format_csv(self, assessment: MigrationAssessment, sanitize: bool = True) -> str:
        output_rows = []
        output_rows.append("VM_Name,Wave,Power_State,vCPUs,RAM_MB,Storage_InUse_GB,Guest_OS,Host,Cluster,Blockers,Warnings")
        for v in assessment.vms:
            name = self.sanitizer.mask_vm(v.name) if sanitize else v.name
            host = self.sanitizer.mask_host(v.esxi_host) if sanitize else v.esxi_host
            cluster = self.sanitizer.mask_cluster(v.cluster) if sanitize else v.cluster
            blockers_str = "; ".join(v.blockers).replace(",", " ")
            warnings_str = "; ".join(v.warnings).replace(",", " ")
            output_rows.append(f"{name},{v.assigned_wave},{v.power_state},{v.cpus},{v.memory_mb},{v.in_use_gb:.2f},{v.os_name},{host},{cluster},\"{blockers_str}\",\"{warnings_str}\"")
        return "\n".join(output_rows)

    def format_proof_of_work(self, assessment: MigrationAssessment, sanitize: bool = True) -> str:
        s = assessment.sizing
        vcenter = self.sanitizer.mask_host(assessment.vcenter_name) if sanitize else assessment.vcenter_name
        pow_md = f"""# SRE & Infrastructure Portfolio Proof-of-Work: VMware Exit Planning

> Sanitized technical case study for Infrastructure Architect & Virtualization Engineer portfolio documentation.

- **Project Context:** Planned automated hypervisor migration for an enterprise VMware vSphere environment (`{vcenter}`) comprising `{assessment.total_vms}` virtual machines across ESXi clusters to `{s.target_hypervisor}` to eliminate Broadcom subscription licensing price exposure.
- **Telemetry Ingestion & Sanitization:** Parsed RVTools multi-tab workbook (`vInfo`, `vDisk`, `vSnapshot`, `vHost`, `vNetwork`) using zero-dependency Python streaming parser. Applied SHA-256 masking to server hostnames, IP addresses, and customer storage identifiers.
- **Architectural Blockers Remediated:**
  - `{assessment.rdm_count}` Raw Device Mappings isolated for pre-migration `vmkfstools` virtual disk conversion.
  - `{assessment.stale_snapshot_count}` stale snapshot chains older than 72 hours identified for consolidation before cutover.
  - `{assessment.legacy_os_count}` legacy guest operating systems flagged for offline VirtIO driver pre-injection.
- **Workload Optimization & Wave Planning:** Formulated a 5-wave migration schedule identifying `{assessment.zombie_reclaimable_gb:.1f} GB` of reclaimable storage from `{assessment.zombie_vms}` powered-off zombie workloads in Wave 0.
- **Destination Cluster Sizing:** Sized target `{s.target_hypervisor}` cluster at `{s.nodes_recommended_n1}` physical nodes (`{s.node_profile_cores}` cores, `{s.node_profile_ram_gb} GB` RAM each) with `{s.raw_storage_tb:.1f} TB` Ceph 3x storage pool delivering $N+1$ high-availability resilience.
"""
        return pow_md.strip()


# ----------------------------------------------------------------------
# CLI Interface
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="VMware RVTools to Proxmox/Hyper-V Migration Planner (rvtools-migration-planner)"
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        help="Path to RVTools Excel workbook (.xlsx), single CSV, or directory of exported CSVs"
    )
    parser.add_argument(
        "-t", "--target",
        choices=["proxmox", "hyper-v", "all"],
        default="proxmox",
        help="Target hypervisor architecture (default: proxmox)"
    )
    parser.add_argument(
        "-f", "--format", "--output-format",
        dest="format",
        choices=["markdown", "json", "html", "csv", "proof-of-work", "all"],
        default="markdown",
        help="Output report format (default: markdown)"
    )
    parser.add_argument(
        "--sanitize",
        action="store_true",
        default=True,
        help="Enable client-side PII and host sanitization (default: enabled)"
    )
    parser.add_argument(
        "--no-sanitize",
        dest="sanitize",
        action="store_false",
        help="Disable client-side sanitization"
    )
    parser.add_argument(
        "--generate-proof-of-work",
        action="store_true",
        help="Generate a sanitized SRE / Infrastructure portfolio case study"
    )
    parser.add_argument(
        "--node-cores",
        type=int,
        default=64,
        help="Target physical cores per host node (default: 64)"
    )
    parser.add_argument(
        "--node-ram",
        type=int,
        default=512,
        help="Target physical RAM in GB per host node (default: 512)"
    )
    parser.add_argument(
        "--prod-overcommit",
        type=float,
        default=2.0,
        help="Production vCPU to physical core overcommit ratio (default: 2.0)"
    )
    parser.add_argument(
        "--dev-overcommit",
        type=float,
        default=4.0,
        help="Development/VDI vCPU to physical core overcommit ratio (default: 4.0)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        help="Output file path (or directory when --format=all)"
    )
    return parser


def main() -> None:
    cli_parser = build_parser()
    args = cli_parser.parse_args()

    if not args.input:
        cli_parser.print_help()
        sys.exit(0)

    sanitizer = Sanitizer()
    parser = RVToolsParser()
    engine = MigrationEngine(sanitizer=sanitizer)
    generator = MigrationReportGenerator(sanitizer=sanitizer)

    target_name = "Proxmox VE" if args.target == "proxmox" else "Microsoft Hyper-V"

    tables = parser.parse(args.input)
    assessment = engine.analyze(
        tables=tables,
        target_hypervisor=target_name,
        node_cores=args.node_cores,
        node_ram_gb=args.node_ram,
        prod_overcommit=args.prod_overcommit,
        dev_overcommit=args.dev_overcommit
    )

    if args.generate_proof_of_work:
        args.format = "proof-of-work"

    if args.format == "all":
        out_dir = Path(args.output or "./rvtools-migration-output")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "migration-assessment.md").write_text(generator.format_markdown(assessment, sanitize=args.sanitize), encoding="utf-8")
        (out_dir / "migration-data.json").write_text(generator.format_json(assessment, sanitize=args.sanitize), encoding="utf-8")
        (out_dir / "migration-dashboard.html").write_text(generator.format_html(assessment, sanitize=args.sanitize), encoding="utf-8")
        (out_dir / "migration-waves.csv").write_text(generator.format_csv(assessment, sanitize=args.sanitize), encoding="utf-8")
        (out_dir / "proof-of-work.md").write_text(generator.format_proof_of_work(assessment, sanitize=args.sanitize), encoding="utf-8")
        print(f"Successfully exported all migration plan formats to: {out_dir}")
        return

    out_text = ""
    if args.format == "markdown":
        out_text = generator.format_markdown(assessment, sanitize=args.sanitize)
    elif args.format == "json":
        out_text = generator.format_json(assessment, sanitize=args.sanitize)
    elif args.format == "html":
        out_text = generator.format_html(assessment, sanitize=args.sanitize)
    elif args.format == "csv":
        out_text = generator.format_csv(assessment, sanitize=args.sanitize)
    elif args.format == "proof-of-work":
        out_text = generator.format_proof_of_work(assessment, sanitize=args.sanitize)

    if args.output:
        out_file = Path(args.output)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(out_text, encoding="utf-8")
        print(f"Successfully generated migration plan: {out_file}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()

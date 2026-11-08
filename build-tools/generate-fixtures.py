#!/usr/bin/env python3
"""
Synthetic RVTools Fixture Generator

Generates 5 realistic, 100% synthetic RVTools test fixture datasets using
pure Python standard library modules (csv, zipfile, xml.etree.ElementTree).

Adheres strictly to Rule 7 (Zero-Emoji Enterprise Tone) and Rule 9 (Obvious Mock Data).
"""

import csv
import datetime
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def create_csv(filepath: Path, headers: list, rows: list) -> None:
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def build_xlsx_file(filepath: Path, sheets: dict) -> None:
    """
    Creates a valid Excel .xlsx workbook containing multiple sheets using
    pure standard library zipfile and XML generation.
    """
    with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # 1. [Content_Types].xml
        content_types = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '  <Default Extension="xml" ContentType="application/xml"/>',
            '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        ]
        for idx in range(1, len(sheets) + 1):
            content_types.append(f'  <Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        content_types.append('</Types>')
        z.writestr("[Content_Types].xml", "\n".join(content_types))

        # 2. _rels/.rels
        rels = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>',
            '</Relationships>'
        ]
        z.writestr("_rels/.rels", "\n".join(rels))

        # 3. Collect unique shared strings
        shared_strings = []
        string_to_idx = {}
        for s_name, (headers, rows) in sheets.items():
            for h in headers:
                if str(h) not in string_to_idx:
                    string_to_idx[str(h)] = len(shared_strings)
                    shared_strings.append(str(h))
            for row in rows:
                for val in row:
                    val_str = str(val)
                    if val_str not in string_to_idx:
                        string_to_idx[val_str] = len(shared_strings)
                        shared_strings.append(val_str)

        ss_xml = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        ]
        for s in shared_strings:
            clean_s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ss_xml.append(f'  <si><t>{clean_s}</t></si>')
        ss_xml.append('</sst>')
        z.writestr("xl/sharedStrings.xml", "\n".join(ss_xml))

        # 4. xl/workbook.xml and xl/_rels/workbook.xml.rels
        wb_xml = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            '  <sheets>'
        ]
        wb_rels = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            f'  <Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        ]

        sheet_idx = 1
        for s_name in sheets.keys():
            wb_xml.append(f'    <sheet name="{s_name}" sheetId="{sheet_idx}" r:id="rId{sheet_idx}"/>')
            wb_rels.append(f'  <Relationship Id="rId{sheet_idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{sheet_idx}.xml"/>')
            sheet_idx += 1

        wb_xml.append('  </sheets>')
        wb_xml.append('</workbook>')
        wb_rels.append('</Relationships>')
        z.writestr("xl/workbook.xml", "\n".join(wb_xml))
        z.writestr("xl/_rels/workbook.xml.rels", "\n".join(wb_rels))

        # 5. Worksheets
        sheet_idx = 1
        for s_name, (headers, rows) in sheets.items():
            ws_xml = [
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
                '  <sheetData>'
            ]
            # Header row (row 1)
            ws_xml.append('    <row r="1">')
            for col_idx, h in enumerate(headers, start=1):
                col_letter = chr(64 + col_idx) if col_idx <= 26 else f"A{chr(64 + col_idx - 26)}"
                val_idx = string_to_idx[str(h)]
                ws_xml.append(f'      <c r="{col_letter}1" t="s"><v>{val_idx}</v></c>')
            ws_xml.append('    </row>')

            # Data rows
            for row_idx, row in enumerate(rows, start=2):
                ws_xml.append(f'    <row r="{row_idx}">')
                for col_idx, val in enumerate(row, start=1):
                    col_letter = chr(64 + col_idx) if col_idx <= 26 else f"A{chr(64 + col_idx - 26)}"
                    val_idx = string_to_idx[str(val)]
                    ws_xml.append(f'      <c r="{col_letter}{row_idx}" t="s"><v>{val_idx}</v></c>')
                ws_xml.append('    </row>')

            ws_xml.append('  </sheetData>')
            ws_xml.append('</worksheet>')
            z.writestr(f"xl/worksheets/sheet{sheet_idx}.xml", "\n".join(ws_xml))
            sheet_idx += 1


def generate_all_fixtures() -> None:
    print("[*] Generating synthetic RVTools test fixtures...")

    # -------------------------------------------------------------
    # Fixture 1: Enterprise Datacenter (Directory of CSVs + .xlsx)
    # -------------------------------------------------------------
    ent_dir = FIXTURES_DIR / "fixture-enterprise-datacenter-csv"
    ent_dir.mkdir(parents=True, exist_ok=True)

    vinfo_headers = ["VM", "Powerstate", "CPUs", "Memory", "Provisioned MiB", "In Use MiB", "OS according to the VM spec", "Host", "Cluster", "Datacenter", "Primary IP Address"]
    vdisk_headers = ["VM", "Disk", "Capacity MiB", "Disk Path", "Controller", "Sharing", "Raw"]
    vsnap_headers = ["VM", "Snapshot", "Date / time snapshot", "Size MiB"]
    vhost_headers = ["Host", "Cluster", "Num CPU", "Cores per CPU", "Memory Size", "ESXi Version"]

    vinfo_rows = []
    vdisk_rows = []
    vsnap_rows = []
    vhost_rows = []

    for h_id in range(1, 9):
        vhost_rows.append([f"mock-esxi-{h_id:02d}.synthetic.local", "Cluster-Production", "2", "16", "262144", "7.0.3"])

    # 100 VMs
    for i in range(1, 101):
        vm_name = f"mock-vm-app-{i:03d}"
        power = "poweredOn" if i <= 85 else "poweredOff"
        cpus = 2 if i % 4 != 0 else 4
        ram = 4096 if i % 2 == 0 else 8192
        prov_mib = 51200
        inuse_mib = 25600
        os_name = "Red Hat Enterprise Linux 8 (64-bit)" if i % 3 != 0 else "Microsoft Windows Server 2019 (64-bit)"
        host = f"mock-esxi-{(i % 8) + 1:02d}.synthetic.local"
        cluster = "Cluster-Production"

        # Inject RDM on VM 12 and 34
        is_rdm = "rawDeviceMapPage" if i in [12, 34] else "flat"
        vdisk_rows.append([vm_name, "Hard disk 1", "51200", f"[datastore-01] {vm_name}/{vm_name}.vmdk", "LSI Logic SAS", "sharingNone", is_rdm])

        # Inject Stale Snapshots on VM 7 and 22
        if i in [7, 22]:
            vsnap_rows.append([vm_name, "pre-patch-backup", "2026-09-15 10:00:00", "25600"])

        # Inject Legacy OS on VM 18 (Win 2003) and VM 45 (CentOS 5)
        if i == 18:
            os_name = "Microsoft Windows Server 2003 (32-bit)"
        elif i == 45:
            os_name = "CentOS 5.8 (64-bit)"

        # Inject Monster VM on VM 50
        if i == 50:
            cpus = 48
            ram = 196608
            prov_mib = 1048576
            inuse_mib = 524288

        vinfo_rows.append([vm_name, power, str(cpus), str(ram), str(prov_mib), str(inuse_mib), os_name, host, cluster, "Datacenter-Core", f"192.0.2.{i % 240 + 1}"])

    create_csv(ent_dir / "vInfo.csv", vinfo_headers, vinfo_rows)
    create_csv(ent_dir / "vDisk.csv", vdisk_headers, vdisk_rows)
    create_csv(ent_dir / "vSnapshot.csv", vsnap_headers, vsnap_rows)
    create_csv(ent_dir / "vHost.csv", vhost_headers, vhost_rows)

    # Also build native .xlsx for Fixture 1
    xlsx_sheets = {
        "vInfo": (vinfo_headers, vinfo_rows),
        "vDisk": (vdisk_headers, vdisk_rows),
        "vSnapshot": (vsnap_headers, vsnap_rows),
        "vHost": (vhost_headers, vhost_rows)
    }
    build_xlsx_file(FIXTURES_DIR / "fixture-enterprise-datacenter.xlsx", xlsx_sheets)

    # -------------------------------------------------------------
    # Fixture 2: Hard Blockers (RDMs, Snapshots, Multi-Writer)
    # -------------------------------------------------------------
    f2_vinfo = [
        ["mock-oracle-rac-node1", "poweredOn", "16", "65536", "204800", "102400", "Oracle Linux 8 (64-bit)", "mock-esxi-01.synthetic.local", "Cluster-Database", "DC-1", "192.0.2.11"],
        ["mock-oracle-rac-node2", "poweredOn", "16", "65536", "204800", "102400", "Oracle Linux 8 (64-bit)", "mock-esxi-02.synthetic.local", "Cluster-Database", "DC-1", "192.0.2.12"],
        ["mock-sql-shared-cluster", "poweredOn", "8", "32768", "153600", "76800", "Microsoft Windows Server 2016", "mock-esxi-01.synthetic.local", "Cluster-Database", "DC-1", "192.0.2.13"],
        ["mock-file-server-rdm", "poweredOn", "4", "16384", "512000", "409600", "Microsoft Windows Server 2019", "mock-esxi-03.synthetic.local", "Cluster-General", "DC-1", "192.0.2.14"],
        ["mock-dev-snapshot-trap", "poweredOn", "2", "8192", "40960", "30720", "Ubuntu Linux (64-bit)", "mock-esxi-03.synthetic.local", "Cluster-General", "DC-1", "192.0.2.15"]
    ]
    f2_vdisk = [
        ["mock-oracle-rac-node1", "Hard disk 1", "51200", "[san-01] rac1/rac1.vmdk", "LSI Logic SAS", "sharingNone", "flat"],
        ["mock-oracle-rac-node1", "Hard disk 2", "153600", "[san-01] shared/ocr.vmdk", "VMware Paravirtual", "sharingMultiWriter", "flat"],
        ["mock-oracle-rac-node2", "Hard disk 1", "51200", "[san-01] rac2/rac2.vmdk", "LSI Logic SAS", "sharingNone", "flat"],
        ["mock-oracle-rac-node2", "Hard disk 2", "153600", "[san-01] shared/ocr.vmdk", "VMware Paravirtual", "sharingMultiWriter", "flat"],
        ["mock-file-server-rdm", "Hard disk 1", "51200", "[san-01] files/boot.vmdk", "LSI Logic SAS", "sharingNone", "flat"],
        ["mock-file-server-rdm", "Hard disk 2", "460800", "vml.0123456789abcdef", "LSI Logic SAS", "sharingNone", "rawDeviceMapPage"]
    ]
    f2_vsnap = [
        ["mock-dev-snapshot-trap", "Snapshot-Old-Dec", "2026-08-10 12:00:00", "28000"]
    ]
    f2_sheets = {
        "vInfo": (vinfo_headers, f2_vinfo),
        "vDisk": (vdisk_headers, f2_vdisk),
        "vSnapshot": (vsnap_headers, f2_vsnap)
    }
    build_xlsx_file(FIXTURES_DIR / "fixture-rdm-and-snapshots-blockers.xlsx", f2_sheets)

    # -------------------------------------------------------------
    # Fixture 3: Legacy OS Fleet (VirtIO Gaps)
    # -------------------------------------------------------------
    f3_vinfo = [
        ["mock-legacy-win2003", "poweredOn", "2", "4096", "30720", "15360", "Microsoft Windows Server 2003 (32-bit)", "mock-esxi-01.synthetic.local", "Cluster-Legacy", "DC-1", "192.0.2.21"],
        ["mock-legacy-win2008r2", "poweredOn", "4", "8192", "61440", "30720", "Microsoft Windows Server 2008 R2 (64-bit)", "mock-esxi-01.synthetic.local", "Cluster-Legacy", "DC-1", "192.0.2.22"],
        ["mock-legacy-centos5", "poweredOn", "2", "2048", "20480", "10240", "CentOS 5.11 (64-bit)", "mock-esxi-02.synthetic.local", "Cluster-Legacy", "DC-1", "192.0.2.23"],
        ["mock-modern-rocky9", "poweredOn", "4", "16384", "51200", "20480", "Rocky Linux 9 (64-bit)", "mock-esxi-02.synthetic.local", "Cluster-Legacy", "DC-1", "192.0.2.24"]
    ]
    create_csv(FIXTURES_DIR / "fixture-legacy-os-fleet.csv", vinfo_headers, f3_vinfo)

    # -------------------------------------------------------------
    # Fixture 4: Monster VMs and Clustered Infrastructure
    # -------------------------------------------------------------
    f4_vinfo = [
        ["mock-sap-hana-db01", "poweredOn", "64", "262144", "1048576", "819200", "SUSE Linux Enterprise Server 15 (64-bit)", "mock-esxi-05.synthetic.local", "Cluster-SAP", "DC-1", "192.0.2.31"],
        ["mock-sap-hana-db02", "poweredOn", "64", "262144", "1048576", "819200", "SUSE Linux Enterprise Server 15 (64-bit)", "mock-esxi-06.synthetic.local", "Cluster-SAP", "DC-1", "192.0.2.32"],
        ["mock-analytics-worker", "poweredOn", "32", "131072", "524288", "307200", "Ubuntu Linux (64-bit)", "mock-esxi-05.synthetic.local", "Cluster-SAP", "DC-1", "192.0.2.33"]
    ]
    f4_sheets = {
        "vInfo": (vinfo_headers, f4_vinfo)
    }
    build_xlsx_file(FIXTURES_DIR / "fixture-monster-vms-and-clustering.xlsx", f4_sheets)

    # -------------------------------------------------------------
    # Fixture 5: Clean Greenfield Cluster (Immediate Cutover Ready)
    # -------------------------------------------------------------
    f5_vinfo = [
        [f"mock-clean-web-{i:02d}", "poweredOn", "2", "4096", "40960", "15360", "Debian GNU/Linux 12 (64-bit)", f"mock-esxi-{(i%3)+1:02d}.synthetic.local", "Cluster-Web", "DC-1", f"192.0.2.{i+50}"]
        for i in range(1, 21)
    ]
    create_csv(FIXTURES_DIR / "fixture-clean-greenfield-cluster.csv", vinfo_headers, f5_vinfo)

    print("[+] Successfully generated all 5 synthetic RVTools fixtures.")


if __name__ == "__main__":
    generate_all_fixtures()

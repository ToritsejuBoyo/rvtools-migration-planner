---
name: rvtools-migration-planner
description: >
  Analyzes VMware vSphere RVTools multi-tab Excel workbooks (.xlsx) and CSV exports (vInfo, vDisk, vSnapshot, vNetwork, vHost) to produce comprehensive Proxmox VE or Microsoft Hyper-V migration assessments, blocker matrices, N+1 cluster capacity sizing, and phased wave cutover plans. Use this skill when a Virtualization Engineer, Infrastructure Architect, or VMware Administrator is planning a Broadcom VMware exit, auditing VM snapshots/RDMs/legacy OS blockers, calculating host CPU/RAM/Ceph/ZFS storage sizing, or scripting automated VM imports.
---

# VMware RVTools to Proxmox / Hyper-V Migration Planner (`rvtools-migration-planner`)

## Overview

Following Broadcom's VMware licensing changes and shift to mandatory per-core subscription bundles, enterprise IT departments, MSPs, and hosting providers are executing hypervisor exit programs toward **Proxmox VE (KVM/QEMU with Ceph/ZFS)** or **Microsoft Windows Server Hyper-V (Storage Spaces Direct)**.

Manual analysis of RVTools Excel workbooks (`vInfo`, `vDisk`, `vSnapshot`, `vNetwork`, `vHost`) across hundreds or thousands of virtual machines is slow and frequently misses catastrophic cutover blockers:
- **Raw Device Mappings (RDMs):** Direct LUN attachments that cannot be migrated via standard V2V disk format conversion.
- **Stale Snapshots (>72 Hours or >20 GB):** Deep delta chains that risk storage exhaustion, corruption, or extended downtime during export.
- **Multi-Writer Clustered Disks:** Oracle RAC or Windows Failover Clustering shared SCSI buses requiring dedicated target storage architecture.
- **Legacy Guest Operating Systems:** Operating systems (Windows 2003/2008, CentOS 5/6, RHEL 4/5) lacking native inbox VirtIO drivers.
- **Monster VMs & vNUMA Topologies:** Workloads with >=32 vCPUs or >=128 GB RAM requiring explicit socket and NUMA node alignment on target hosts.
- **Sub-optimal Cluster Sizing:** Failing to enforce N+1 or N+2 High Availability reservations and Ceph 3x storage replication overhead.

This skill provides a zero-dependency Python engine (`scripts/rvtools_planner.py`) that ingests native multi-tab RVTools `.xlsx` workbooks and `.csv` directories, identifies blockers, computes deterministic destination cluster sizing, and outputs structured Markdown and JSON assessment deliverables.

---

## Operating Rules & Safety Guardrails

1. **Read-Only Offline Telemetry (Rule 3):**
   - The analysis engine operates strictly offline on static RVTools `.xlsx` or `.csv` exports.
   - Never initiate live network connections to production vCenter, ESXi, Proxmox VE, or Hyper-V environments.
2. **Mandatory Client-Side Sanitization (Rule 4):**
   - When `--sanitize` is passed, the engine deterministically masks VM names (`vm-0001`), ESXi hosts (`esxi-01.internal`), clusters (`cluster-a`), datastores (`datastore-01`), and IP addresses (`192.0.2.x`).
   - Guarantees zero sensitive customer telemetry or internal IP ranges leave the local environment or touch an LLM.
3. **Deterministic Cluster Capacity Sizing:**
   - Compute: Enforce configurable vCPU to physical core (pCore) overcommit ratios (default 2.0:1 for production, 4.0:1 for dev/test).
   - Memory: Enforce non-overcommitted physical RAM sizing with a 10% hypervisor and ZFS/Ceph ARC buffer.
   - Storage: Automatically compute Ceph 3x replication factors and a 20% maintenance headroom buffer for metadata, scrub operations, and dynamic recovery.
   - High Availability: Enforce $N+1$ host resilience for clusters up to 8 nodes, and $N+2$ for clusters exceeding 8 nodes.
4. **Windows VirtIO Controller Safety:**
   - Explicitly flag Windows workloads with Paravirtual SCSI (PVSCSI) or LSI Logic SAS controllers requiring offline VirtIO driver injection prior to target boot to avoid `INACCESSIBLE_BOOT_DEVICE` (Bugcheck 0x7B) bluescreens.

---

## Telemetry Ingestion & Usage

### Mode A: Comprehensive CLI Engine (Recommended)

Run the bundled zero-dependency Python script directly against your RVTools `.xlsx` workbook or exported CSV directory:

```bash
# Analyze native multi-tab RVTools Excel workbook for Proxmox VE
python scripts/rvtools_planner.py \
  --input ./RVTools_export.xlsx \
  --target proxmox \
  --cores 64 \
  --ram 512 \
  --sanitize \
  --output ./rvtools-migration-report.md

# Analyze exported CSV directory for Microsoft Hyper-V
python scripts/rvtools_planner.py \
  --input ./rvtools-csv-folder/ \
  --target hyperv \
  --cores 32 \
  --ram 256 \
  --sanitize \
  --json-output ./rvtools-assessment.json
```

### Mode B: Direct Summary / Snippet Paste

If running in an interactive LLM session without local script execution, paste the summary metrics or raw rows from RVTools tabs:
- `vInfo`: VM, Powerstate, CPUs, Memory, Provisioned MiB, In Use MiB, OS according to the VM spec.
- `vDisk`: VM, Disk, Controller, Sharing, Capacity MiB, Raw.
- `vSnapshot`: VM, Snapshot, Date / Time, Size MiB.

The agent applies the rules defined in `references/hypervisor-migration-matrix.md` and generates the assessment plan.

---

## Diagnostic Workflow & Sizing Methodology

```
┌────────────────────────────────────────────────────────┐
│         1. RVTools Ingestion (.xlsx or .csv)           │
│   (vInfo: compute | vDisk: storage | vSnapshot: delta) │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│     2. Blocker & Architectural Constraint Audit        │
│   - Physical/Virtual RDMs (Cutover blocker)            │
│   - Stale Snapshots >72h (Storage explosion risk)      │
│   - Multi-writer SCSI bus (Oracle RAC / MSCS)          │
│   - Legacy Guest OS (Windows 2003/2008, CentOS 5)      │
│   - Monster VMs (vCPU >= 32 or RAM >= 128GB)           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│       3. Phased 5-Wave Migration Partitioning          │
│   - Wave 0: Decommission / Zombie VMs (Reclaim disk)   │
│   - Wave 1: Pilot & Stateless Dev/Test Linux           │
│   - Wave 2: Tier-2 Internal Web & Application Tiers    │
│   - Wave 3: Tier-1 Production Databases & Core Apps    │
│   - Wave 4: Complex, Clustered, and Blocker Workloads  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│    4. Deterministic Destination Cluster Sizing         │
│   - Proxmox VE: Ceph 3x Replication + N+1 Node HA      │
│   - Hyper-V: S2D 3-way Mirror + 16-Core Server License │
└────────────────────────────────────────────────────────┘
```

---

## Migration Wave Partitioning Criteria

| Wave Index | Target Scope | Workload Characteristics | Pre-Cutover Requirements |
| :--- | :--- | :--- | :--- |
| **Wave 0** | Decommission & Cleanup | Powered-off, orphaned, and zombie VMs | Confirm with application owners; archive or delete to reclaim storage capacity. |
| **Wave 1** | Pilot & Low-Risk | Stateless dev/test Linux (Ubuntu, Debian, RHEL) | Validate bridge networking, VLAN tags, and backup integration (Proxmox Backup Server / Veeam). |
| **Wave 2** | Tier-2 Business Apps | Internal web applications, build agents, analytics | Verify storage IOPS, configure DNS TTLs, execute non-disruptive migration. |
| **Wave 3** | Tier-1 Stateful Core | Standalone databases (SQL Server, PostgreSQL), ERP | Schedule maintenance windows, stage pre-sync replication, execute final delta sync. |
| **Wave 4** | High-Risk & Blockers | Clustered Oracle RAC, MSCS, RDMs, Monster VMs | Convert RDMs to virtual disks, configure shared Ceph RBD / S2D shared VHDX, inject VirtIO drivers. |

---

## Destination Cluster Sizing Mathematics

### 1. Compute & Processor Sizing
$$\text{Required Physical Cores} = \max\left(16, \left\lceil \frac{\text{Active vCPUs}}{\text{vCPU:pCore Overcommit Ratio}} \right\rceil\right)$$
- Default Production Overcommit: `2.0:1`
- Default Dev/Test Overcommit: `4.0:1`

### 2. Memory Sizing
$$\text{Required Physical RAM (GB)} = \max\left(64, \left\lceil \text{Active vRAM} \times 1.05 \times 1.10 \right\rceil\right)$$
- Accounts for 5% dynamic guest overhead and 10% host OS, KVM kernel, and ZFS ARC / Ceph OSD daemon memory buffers.

### 3. Storage Sizing
$$\text{Usable Storage Pool (TB)} = \frac{\text{Total In-Use Storage (GB)} \times 1.20}{1024}$$
$$\text{Raw Storage Capacity (TB)} = \text{Usable Storage (TB)} \times \text{Replication Factor}$$
- Proxmox Ceph 3-Replica Factor: `3.0`
- Microsoft Hyper-V S2D 3-Way Mirror Factor: `3.0`
- Includes mandatory 20% maintenance headroom for rebalance, recovery, and scrub spikes.

### 4. High Availability (HA) Node Configuration
$$\text{Base Active Nodes} = \max\left(3, \left\lceil \frac{\text{Required pCores}}{\text{Node pCores}} \right\rceil, \left\lceil \frac{\text{Required RAM}}{\text{Node RAM}} \right\rceil\right)$$
$$\text{Recommended Cluster Nodes} = \text{Base Active Nodes} + 1 \quad (\text{or } +2 \text{ if cluster} > 8 \text{ nodes})$$

---

## Bundled Tools & Resources

- **Core Analysis Engine:** [`scripts/rvtools_planner.py`](scripts/rvtools_planner.py) — Native Python 3 CLI engine supporting streaming OpenXML `.xlsx` and `.csv` parsing, blocker identification, sanitization, and sizing calculations.
- **Architectural Reference Matrix:** [`references/hypervisor-migration-matrix.md`](references/hypervisor-migration-matrix.md) — Comprehensive reference on Broadcom licensing changes, RDM migration alternatives, snapshot risks, Ceph/ZFS storage math, and Windows VirtIO injection runbooks.
- **Migration Assessment Report Template:** [`assets/rvtools-migration-report-template.md`](assets/rvtools-migration-report-template.md) — Production-grade Markdown template for enterprise migration reports and executive deliverables.
- **Automated Test Suites:**
  - Standard Test Harness: [`tests/validate-skill.py`](tests/validate-skill.py)
  - Scale Stress Test: [`tests/stress_test_rvtools_planner.py`](tests/stress_test_rvtools_planner.py)
  - Extreme Malformed Payload Test: [`tests/extreme_test_rvtools_planner.py`](tests/extreme_test_rvtools_planner.py)
  - Architectural Edge Cases Test: [`tests/advanced_edge_cases_test.py`](tests/advanced_edge_cases_test.py)

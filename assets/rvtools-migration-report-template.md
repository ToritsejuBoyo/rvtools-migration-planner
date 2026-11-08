# VMware Migration Assessment & Sizing Plan (`rvtools-migration-planner`)

**Assessment ID:** `VMMIG-{{DATE}}-{{ASSESSMENT_HASH}}`
**Source vCenter / Cluster:** `{{VCENTER_NAME}}` / `{{CLUSTER_COUNT}} Clusters` (ESXi Hosts: `{{HOST_COUNT}}`)
**Target Hypervisor:** `{{TARGET_HYPERVISOR}}` *(Proxmox VE / Microsoft Hyper-V)*
**Report Generated:** `{{GENERATED_DATE}}`

---

## 1. Executive Summary & Inventory Metrics

| Virtualization Dimension | Source Inventory Metric | Migration Analysis & Optimization |
| :--- | :--- | :--- |
| **Total Virtual Machines** | `{{TOTAL_VMS}}` VMs | `{{POWERED_ON_VMS}}` Active / `{{POWERED_OFF_VMS}}` Powered Off |
| **Zombie / Stale Workloads** | `{{ZOMBIE_VM_COUNT}}` VMs (Powered off >90d) | **Wave 0 Cleanup Candidate:** Reclaims `{{ZOMBIE_RECLAIMABLE_GB}} GB` |
| **Total Compute Capacity** | `{{TOTAL_VCPU}}` vCPUs | Active vCPUs: `{{ACTIVE_VCPU}}` |
| **Total Memory Capacity** | `{{TOTAL_RAM_GB}} GB` Provisioned | Active Memory: `{{ACTIVE_RAM_GB}} GB` |
| **Total Storage In-Use** | `{{TOTAL_STORAGE_GB}} GB` In-Use | Provisioned: `{{TOTAL_PROVISIONED_STORAGE_GB}} GB` |
| **Migration Readiness Score** | `{{READINESS_PERCENTAGE}}%` Ready | `{{BLOCKER_COUNT}}` Critical Blockers / `{{WARNING_COUNT}}` Warnings |

---

## 2. Critical Blockers & Architectural Constraints Matrix

| Risk Level | Constraint Type | Target VM | Technical Issue / Detail | Mandatory Pre-Migration Action |
| :--- | :--- | :--- | :--- | :--- |
| **Critical** | `Raw Device Mapping (RDM)` | `{{RDM_VM_NAME}}` | Disk `{{RDM_DISK_NAME}}` mapped as physical LUN | Convert RDM to VMDK via `vmkfstools -i` or present target iSCSI LUN. |
| **Critical** | `Stale Snapshots` | `{{SNAP_VM_NAME}}` | Snapshot `{{SNAP_NAME}}` (Age: `{{SNAP_AGE_DAYS}}` days, `{{SNAP_SIZE_MB}}` MB) | Consolidate and delete snapshot chain before cutover to prevent CBT failure. |
| **Critical** | `Multi-Writer Disk` | `{{SHARED_VM_NAME}}` | Clustered disk configured with `sharingMultiWriter` | Re-architect as shared Ceph RBD / Shared VHDX or use application replication. |
| **Warning** | `VirtIO Driver Gap` | `{{LEGACY_VM_NAME}}` | Guest OS `{{LEGACY_OS}}` lacks inbox VirtIO drivers | Pre-inject VirtIO storage and network drivers before booting on KVM. |
| **Warning** | `Monster VM` | `{{MONSTER_VM_NAME}}` | Sized with `{{MONSTER_VCPU}}` vCPUs and `{{MONSTER_RAM_GB}} GB` RAM | Configure explicit vNUMA topology matching target physical socket architecture. |

---

## 3. Phased Migration Wave Plan

```
[Wave 0: Decommission & Cleanup] ──► {{WAVE_0_COUNT}} VMs ({{WAVE_0_STORAGE_GB}} GB storage reclaimed)
[Wave 1: Pilot & Low-Risk]       ──► {{WAVE_1_COUNT}} VMs (Stateless dev/test Linux & Windows)
[Wave 2: Tier-2 Business Apps]   ──► {{WAVE_2_COUNT}} VMs (Internal tools, web frontends, microservices)
[Wave 3: Tier-1 Stateful Apps]   ──► {{WAVE_3_COUNT}} VMs (Standalone databases, ERP core, domain controllers)
[Wave 4: Complex / High-Risk]    ──► {{WAVE_4_COUNT}} VMs (Monster VMs, clustered nodes, RDM workloads)
```

### Detailed Wave Allocation

#### Wave 0: Decommission & Stale Workload Removal
- **Scope:** Powered off > 90 days, template artifacts, test VMs.
- **Action:** Archive or decommission in vCenter before replication begins.
- **VM Candidates:** `{{WAVE_0_VM_LIST}}`

#### Wave 1: Pilot & Low-Risk Workloads
- **Scope:** Non-production workloads, single virtual disk, modern VirtIO-compatible OS.
- **Estimated Duration:** 1 business day.
- **VM Candidates:** `{{WAVE_1_VM_LIST}}`

#### Wave 2: Standard Tier-2 Business Workloads
- **Scope:** Multi-disk stateless applications, web servers, testing environments.
- **Estimated Duration:** 2-3 business days.
- **VM Candidates:** `{{WAVE_2_VM_LIST}}`

#### Wave 3: Tier-1 Production Stateful Applications
- **Scope:** Production application servers, standalone databases, Active Directory DCs.
- **Estimated Duration:** 3-5 business days (weekend cutover windows).
- **VM Candidates:** `{{WAVE_3_VM_LIST}}`

#### Wave 4: Complex Workloads & Clustered Infrastructure
- **Scope:** Monster VMs (>32 vCPUs), RDM converted disks, multi-writer shared nodes.
- **Estimated Duration:** Dedicated maintenance windows with vendor validation.
- **VM Candidates:** `{{WAVE_4_VM_LIST}}`

---

## 4. Target Destination Cluster Sizing

### Sizing Parameters & Baseline Assumptions
- **Target Hypervisor Stack:** `{{TARGET_HYPERVISOR}}`
- **vCPU Overcommit Ratio:** Production `{{PROD_VCPU_RATIO}}:1` | Non-Production `{{DEV_VCPU_RATIO}}:1`
- **Storage Resilience:** `{{STORAGE_TYPE}}` (Replication Factor: `{{STORAGE_REPLICATION_FACTOR}}`x) + 20% Headroom
- **Target Node Hardware Profile:** `{{TARGET_NODE_CPU_CORES}}` Cores per Node | `{{TARGET_NODE_RAM_GB}} GB` RAM per Node

### Sizing Output Matrix

| Infrastructure Dimension | Required Resource Capacity | Sizing Calculation |
| :--- | :--- | :--- |
| **Physical CPU Cores** | `{{REQUIRED_PCORES}}` Cores | `{{ACTIVE_VCPU}}` vCPUs / `{{PROD_VCPU_RATIO}}` overcommit |
| **Physical Host Memory** | `{{REQUIRED_PRAM_GB}} GB` RAM | `{{ACTIVE_RAM_GB}} GB` vRAM + 10% Hypervisor/ZFS ARC buffer |
| **Usable Storage Pool** | `{{REQUIRED_USABLE_STORAGE_TB}} TB` | `{{TOTAL_STORAGE_GB}} GB` in-use + 20% snapshot/maintenance headroom |
| **Raw Storage Required** | `{{REQUIRED_RAW_STORAGE_TB}} TB` | `{{REQUIRED_USABLE_STORAGE_TB}} TB` $\times$ `{{STORAGE_REPLICATION_FACTOR}}` |
| **Recommended Cluster Nodes** | `{{RECOMMENDED_NODES}}` Nodes | Includes `{{HA_BUFFER_NODES}}` node ($N+1$ / $N+2$ High Availability buffer) |

---

## 5. Automated Target Import Runbook (Proxmox VE)

Execute the following commands on target Proxmox VE nodes to provision and attach converted virtual disks:

```bash
# 1. Create target VM configuration
qm create {{SAMPLE_VM_ID}} \
  --name "{{SAMPLE_VM_NAME}}" \
  --memory {{SAMPLE_VM_RAM_MB}} \
  --cores {{SAMPLE_VM_CORES}} \
  --sockets 1 \
  --cpu host \
  --ostype l26 \
  --scsihw virtio-scsi-single \
  --net0 virtio,bridge=vmbr0

# 2. Import converted virtual disk to target storage pool
qm importdisk {{SAMPLE_VM_ID}} {{SAMPLE_VM_DISK_PATH}} {{TARGET_STORAGE_POOL}} --format raw

# 3. Attach imported volume to VirtIO SCSI controller
qm set {{SAMPLE_VM_ID}} --scsi0 {{TARGET_STORAGE_POOL}}:vm-{{SAMPLE_VM_ID}}-disk-0,discard=on,ssd=1
qm set {{SAMPLE_VM_ID}} --boot order=scsi0
```

---

## 6. Verified Proof-of-Work Case Study (`--generate-proof-of-work`)

> *Sanitized architectural case study for Virtualization & Cloud Engineering portfolio documentation.*

- **Migration Assessment Context:** Evaluated enterprise VMware vSphere environment (`{{SANITIZED_VCENTER}}`) comprising `{{TOTAL_VMS}}` virtual machines across `{{HOST_COUNT}}` ESXi hosts planning hypervisor exit to `{{TARGET_HYPERVISOR}}`.
- **Telemetry Ingestion & Sanitization:** Parsed RVTools multi-tab inventory (`vInfo`, `vDisk`, `vSnapshot`, `vHost`, `vNetwork`) using zero-dependency streaming parser. Applied SHA-256 masking to all server hostnames, IP addresses, and customer datastore identifiers.
- **Architectural Blockers Isolated:** Identified `{{RDM_COUNT}}` Raw Device Mappings requiring pre-migration disk conversion, `{{STALE_SNAP_COUNT}}` stale snapshot chains older than 72 hours, and `{{LEGACY_OS_COUNT}}` legacy operating systems requiring VirtIO driver pre-injection.
- **Capacity & Sizing Deliverable:** Designed a 5-wave migration schedule identifying `{{ZOMBIE_RECLAIMABLE_GB}} GB` of reclaimable storage from zombie workloads. Sized target `{{TARGET_HYPERVISOR}}` cluster at `{{RECOMMENDED_NODES}}` nodes delivering $N+1$ high-availability failover.
- **Measurable Business Impact:** Accelerated migration wave scheduling from 3 weeks of manual spreadsheet analysis to 5 seconds of deterministic processing, eliminating Broadcom renewal cost exposure.

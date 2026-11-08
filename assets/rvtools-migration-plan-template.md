# VMware vSphere to {{TARGET_PLATFORM}} Migration Plan & Sizing Report

**Assessment ID:** `MIG-PLAN-{{DATE}}`
**Source Environment:** VMware vSphere (RVTools Export Analysis)
**Target Platform:** `{{TARGET_PLATFORM}}`
**Total Analyzed VMs:** `{{TOTAL_VMS}}` (`{{POWERED_ON_VMS}}` Powered On / `{{POWERED_OFF_VMS}}` Powered Off)

---

## 1. Executive Inventory & Readiness Summary

| Metric | Active (`poweredOn`) Fleet | Total Provisioned Fleet |
| --- | --- | --- |
| **Virtual Machines** | `{{POWERED_ON_VMS}}` | `{{TOTAL_VMS}}` |
| **Allocated vCPUs** | `{{ACTIVE_VCPUS}}` vCPUs | `{{TOTAL_VCPUS}}` vCPUs |
| **Allocated vRAM** | `{{ACTIVE_RAM_GIB}}` GiB | `{{TOTAL_RAM_GIB}}` GiB |
| **Storage (Provisioned / Consumed)** | `{{ACTIVE_PROV_TIB}}` TiB / `{{ACTIVE_INUSE_TIB}}` TiB | `{{TOTAL_PROV_TIB}}` TiB |

### Migration Readiness Classification
- **Green (Ready for Automated Import):** `{{GREEN_COUNT}}` VMs — Standard BIOS/UEFI VMs with no RDMs, no snapshots, and standard vCPU/RAM profiles.
- **Amber (Pre-Migration Prep Required):** `{{AMBER_COUNT}}` VMs — Require VirtIO driver injection, snapshot consolidation, MAC-pinned Netplan config, or BitLocker suspension.
- **Red (Architecture / Storage Refactor Required):** `{{RED_COUNT}}` VMs — Attach Raw Device Mappings (RDMs), shared multi-writer SCSI cluster disks, or run end-of-support legacy OS versions.

---

## 2. Target Cluster Hardware Sizing (`N+1` High Availability)

| Resource Layer | Sizing Basis & Guardrail Formula | Recommended Target Specification |
| --- | --- | --- |
| **Cluster Node Count** | `{{ACTIVE_NODES}}` Active Nodes + `1` HA Failover Node (`N+1`) | **`{{TOTAL_NODES_N_PLUS_1}}` Physical Host Nodes** |
| **Host CPU Specification** | `{{VCPU_RATIO}}:1` vCPU:pCore ratio (`{{REQ_PCORES}}` pCores needed) | **`{{HOST_CORES}}` Physical Cores per Node** (Dual-Socket or High-Core EPYC/Xeon) |
| **Host Memory Specification** | Zero RAM overcommit + 15% Hypervisor/Storage overhead + 80% load cap | **`{{HOST_RAM_GIB}}` GiB DDR5 ECC RAM per Node** |
| **Primary Storage Capacity** | `{{ACTIVE_PROV_TIB}}` TiB Usable + Replication & Headroom | **`{{RAW_STORAGE_TIB}}` TiB Raw Enterprise NVMe** (`{{STORAGE_ARCHITECTURE}}`) |
| **Network Fabric** | Segregated Management, VM VLAN Trunks, Live Migration & Storage | Dual `25GbE / 100GbE` LACP/MPIO NICs per Node |

---

## 3. Flagged Workloads & Blocker Remediation Matrix

| VM Identifier | Guest OS | vCPU / RAM | Firmware | Readiness | Identified Blockers & Required Pre-Work |
| --- | --- | --- | --- | --- | --- |
| `{{VM_1}}` | `{{OS_1}}` | `{{SPEC_1}}` | `{{FW_1}}` | `{{SEV_1}}` | {{BLOCKER_1}} |
| `{{VM_2}}` | `{{OS_2}}` | `{{SPEC_2}}` | `{{FW_2}}` | `{{SEV_2}}` | {{BLOCKER_2}} |
| `{{VM_3}}` | `{{OS_3}}` | `{{SPEC_3}}` | `{{FW_3}}` | `{{SEV_3}}` | {{BLOCKER_3}} |

---

## 4. Phased 4-Wave Migration Schedule

1. **Wave 0 — Pilot & Validation (`10%` of Fleet / Non-Prod):**
   - Validate ESXi-to-{{TARGET_PLATFORM}} storage import pipeline, VLAN trunking, backup verification (Proxmox Backup Server / Veeam), and monitoring agents.
2. **Wave 1 — Low-Complexity Production (`Green` Workloads):**
   - Stateless web/application servers and Linux VMs with MAC-pinned network configurations.
3. **Wave 2 — Standard Production (`Amber` Workloads):**
   - Windows Server workloads with pre-injected VirtIO (`vioscsi`/`NetKVM`) drivers, consolidated snapshots, and UEFI/vTPM state migration.
4. **Wave 3 — Stateful & Clustered Workloads (`Red` Workloads):**
   - Database clusters, RDM-backed workloads re-pointed to in-guest iSCSI/NVMe-oF, and Active Directory Domain Controller replica replacement.

---

## 5. Pre-Cutover Technical Runbook Commands

### A. Windows Guest Pre-Cutover Prep (Run Inside Source VM Before Shutdown)
```powershell
# 1. Verify no BitLocker encryption is active or suspend protection for cutover
Manage-bde -status
Suspend-BitLocker -MountPoint "C:" -RebootCount 2

# 2. Stage Red Hat VirtIO SCSI and Network drivers from mounted virtio-win ISO (if migrating to Proxmox VE)
pnputil.exe /add-driver "D:\vioscsi\2k22\amd64\vioscsi.inf" /install
pnputil.exe /add-driver "D:\NetKVM\2k22\amd64\netkvm.inf" /install
pnputil.exe /add-driver "D:\Balloon\2k22\amd64\balloon.inf" /install
```

### B. Linux Guest Network MAC Pinning (Prevent `ens192` -> `ens18` Outage)
```yaml
# /etc/netplan/01-netcfg.yaml — Bind interface by MAC address prior to shutdown
network:
  version: 2
  ethernets:
    primary_nic:
      match:
        macaddress: "{{SOURCE_VM_MAC_ADDRESS}}"
      set-name: eth0
      addresses:
        - {{STATIC_IP_CIDR}}
      routes:
        - to: default
          via: {{DEFAULT_GATEWAY}}
```

---

## 6. Verified Proof-of-Work Case Study (`--generate-proof-of-work`)

> *Sanitized virtualization architecture case study for engineering portfolio publication.*

- **Project Scope:** Evaluated a `{{TOTAL_VMS}}`-VM VMware vSphere environment (`{{ACTIVE_VCPUS}}` active vCPUs, `{{ACTIVE_RAM_GIB}}` GiB vRAM, `{{ACTIVE_PROV_TIB}}` TiB provisioned storage) for migration to `{{TARGET_PLATFORM}}`.
- **Automated Discovery & Risk Scoring:** Executed `analyze_rvtools.py` across exported RVTools datasets (`vInfo`, `vDisk`, `vSnapshot`, `vNetwork`), classifying `{{GREEN_COUNT}}` Green, `{{AMBER_COUNT}}` Amber, and `{{RED_COUNT}}` Red workloads.
- **Key Blockers Mitigated:** Isolated RDM-attached storage volumes, multi-writer cluster disks, active snapshot chains, Windows `PVSCSI`-to-`VirtIO` boot driver requirements, and Linux PCI-slot NIC renaming risks.
- **Target Architecture Sized:** Engineered an `{{TOTAL_NODES_N_PLUS_1}}`-node `N+1` high-availability cluster with zero memory overcommit and resilient `{{STORAGE_ARCHITECTURE}}` storage (`{{RAW_STORAGE_TIB}}` TiB raw capacity), paired with a 4-wave cutover runbook.

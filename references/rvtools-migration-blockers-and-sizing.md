# VMware RVTools Migration Blockers, Guest Prep & Cluster Sizing Reference

## 1. RVTools Tab & Column Mapping Matrix

| RVTools CSV Tab | Key Columns to Inspect | Migration Significance |
| --- | --- | --- |
| `tabvInfo.csv` | `VM`, `Powerstate`, `Template`, `CPUs`, `Memory`, `Provisioned MiB`, `In Use MiB`, `Firmware`, `OS according to the configuration file` | Core compute/storage inventory, BIOS vs. UEFI (`efi`) boot mode, and guest OS identification. |
| `tabvDisk.csv` | `VM`, `Disk`, `Capacity MiB`, `Raw`, `Sharing mode`, `Thin`, `Controller` | Identifies **Raw Device Mappings (`Raw = True`)**, multi-writer shared SCSI disks, and `PVSCSI` vs. `LSI Logic` controllers. |
| `tabvSnapshot.csv` | `VM`, `Name`, `Date / time`, `Size MiB (vmsn)`, `Size MiB (total)` | Active delta `.vmdk` snapshot chains that can corrupt or severely slow down V2V disk conversions. |
| `tabvNetwork.csv` | `VM`, `Network`, `Adapter`, `Mac Address`, `IPv4 Address` | Maps VMware port groups (VLANs), `VMXNET3` vs. `E1000` adapters, and static MAC/IP bindings. |
| `tabvHost.csv` | `Host`, `CPU Model`, `# CPU`, `# Cores`, `Memory`, `ESX Version` | Baseline physical host hardware comparison and CPU instruction set generation (Intel Xeon vs. AMD EPYC). |

---

## 2. Technical Migration Blockers & Remediation Playbook

### Blocker A: Windows Boot Disk `INACCESSIBLE_BOOT_DEVICE` (0x0000007B)
- **Cause:** Windows VMs using VMware Paravirtual SCSI (`PVSCSI`) do not have Red Hat `VirtIO SCSI` (`vioscsi.sys`) or `VirtIO Block` (`viostor.sys`) drivers registered in the `HKLM\SYSTEM\CurrentControlSet\Services` boot-start registry hive by default.
- **Safe Remediation (Proxmox VE):**
  1. **Option 1 (Pre-Cutover Driver Injection):** Mount `virtio-win.iso` inside the running VMware VM before shutdown and install `virtio-win-guest-tools.exe` (`pnputil /add-driver E:\vioscsi\w11\amd64\*.inf /install`).
  2. **Option 2 (Two-Step Controller Boot):** Import the Windows boot disk attached to an emulated **`SATA` or `LSI 53C895A`** controller first, attach a tiny 1 GB dummy disk on **`VirtIO SCSI Single`**, boot Windows, install the VirtIO drivers, shut down, and switch the boot disk from SATA to `VirtIO SCSI`.

### Blocker B: Linux Predictable Network Interface Renaming (`ens192` -> `ens18`)
- **Cause:** Modern Linux distributions (Ubuntu 20.04+, Debian 11/12, RHEL 8/9) derive NIC interface names from the virtual PCI slot topology. Moving from VMware (`VMXNET3` on PCI bus) to Proxmox (`VirtIO` on PCI slot 18) changes the interface name from `ens160`/`ens192` to `ens18`, breaking static IP configs in `/etc/netplan/` or `/etc/NetworkManager/system-connections/`.
- **Safe Remediation:**
  - Pin the network configuration by **MAC address** (`match: macaddress: ...`) in Netplan or NetworkManager *before* shutting down the source VMware VM, and preserve the VMware MAC address on the target Proxmox/Hyper-V NIC during initial cutover.

### Blocker C: Raw Device Mappings (RDM) & Shared Multi-Writer Disks
- **Cause:** VMs with `Raw = True` bypass VMFS and talk directly to Fibre Channel or iSCSI SAN LUNs.
- **Safe Remediation:**
  - **Virtual Mode RDM:** Convert to a standard thick/thin virtual disk during storage migration if storage capacity permits.
  - **Physical Mode RDM / Failover Cluster Disks:** Disconnect the RDM prior to V2V conversion, migrate the OS boot disk, and reconnect the shared LUN directly inside the guest OS via the **in-guest iSCSI Initiator** (`iscsicli` / `open-iscsi`) or attach as a Proxmox/Hyper-V pass-through LUN (`qm set <vmid> -scsi2 /dev/disk/by-id/dm-uuid-mpath-...`).

### Blocker D: Active Directory Domain Controllers (AD DS)
- **Cause:** Offline V2V migration of a running Domain Controller risks USN (Update Sequence Number) rollback or InvocationID reset if snapshots are mishandled.
- **Best Practice:** For Active Directory Domain Controllers, **prefer provisioning fresh Windows Server VMs** on Proxmox/Hyper-V, promoting them as replica DCs (`Install-ADDSDomainController`), transferring FSMO roles (`Move-ADDirectoryServerOperationMasterRole`), and demoting the old VMware DCs cleanly.

---

## 3. Target Cluster Hardware Sizing Formulas

### Compute Sizing (`pCores`)
$$\text{Required Physical Cores} = \left\lceil \frac{\sum \text{Active vCPUs}}{\text{Target Consolidation Ratio}} \right\rceil$$
- **General Server / Mixed Virtualization:** `4:1` vCPU:pCore ratio.
- **Tier-1 Production Databases / Heavy ERP:** `2:1` vCPU:pCore ratio.
- **VDI / Dev-Test:** `6:1` to `8:1` vCPU:pCore ratio.
- **NUMA Rule:** No single VM's vCPU count should exceed the physical core count of a single CPU socket on the target host without enabling guest NUMA (`numa: 1`).

### Memory Sizing (`N+1` High Availability)
Never rely on memory overcommit (ballooning/KSM) for production sizing:
$$\text{Node Count } (N_{\text{total}}) = \left\lceil \frac{\sum \text{Active VM RAM} \times 1.15}{\text{Host RAM} \times 0.80} \right\rceil + 1$$
- **`1.15` Multiplier:** Reserves 15% RAM for the hypervisor host OS, Ceph OSD daemons (~4 GB per OSD), or ZFS ARC cache.
- **`0.80` Divisor:** Ensures normal operating load stays at or below 80% per node.
- **`+ 1` Node:** Guarantees full N+1 HA failover capacity.

### Storage Sizing (Hyperconverged Ceph vs. ZFS vs. SAN/S2D)
- **Proxmox + Ceph (3-Replica Pool):**
  $$\text{Raw NVMe Capacity} = \text{Provisioned Usable TiB} \times 3 \times 1.25$$
  *(Includes 3x replication factor and 25% Ceph `nearfull_ratio` / rebalance safety headroom; requires dedicated 25GbE/100GbE storage network).*
- **Proxmox + ZFS RAID10 / Hyper-V S2D 2-Way Mirror:**
  $$\text{Raw Capacity} = \text{Provisioned Usable TiB} \times 2 \times 1.20$$
  *(Includes 2x mirror overhead and 20% ZFS fragmentation headroom).*

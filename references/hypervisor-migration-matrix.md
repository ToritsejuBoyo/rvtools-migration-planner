# Hypervisor Migration Technical Reference: VMware Exit to Proxmox VE & Hyper-V

## 1. VMware Broadcom Licensing Shift & Economic Context

Following Broadcom's acquisition of VMware in late 2023, the virtualization industry experienced fundamental licensing restructuring:
- **Perpetual Licenses Terminated:** Elimination of perpetual licensing with active Support and Subscription (SnS). Organizations must transition to subscription bundles upon renewal.
- **Per-Core Metric Enforcement:** vSphere is now licensed strictly on a per-core basis with a minimum threshold of 16 cores per physical CPU socket.
- **Product Portfolio Consolidation:** Discontinuation of vSphere Standard, Enterprise Plus standalone, and vSphere Essentials Plus. Workloads are funneled into either VMware vSphere Foundation (VVF) or VMware Cloud Foundation (VCF), forcing customers to pay for unused components (vSAN, Aria, NSX).
- **Free ESXi Hypervisor Discontinued:** Complete removal of free vSphere Hypervisor (ESXi free edition), leaving smaller environments and branch offices without zero-cost virtualization.

---

## 2. Target Hypervisor Architectures

### Proxmox Virtual Environment (PVE)
Proxmox VE is an enterprise open-source virtualization platform combining KVM hypervisor technology and Linux Containers (LXC) on Debian Linux:
- **Storage Backends:**
  - **Ceph Software-Defined Storage:** Clustered, highly scalable, block storage (`RBD`) with 3x replication factor. Eliminates traditional SAN/NAS single points of failure.
  - **ZFS on Linux:** Local software RAID (mirror, RAIDZ1, RAIDZ2) providing copy-on-write snapshots, end-to-end data integrity checksums, and native replication via `pvesr`.
- **High Availability & Clustering:** Corosync cluster engine supporting live VM migration without shared SAN when using ZFS asynchronous replication or Ceph.
- **Proxmox Backup Server (PBS):** Client-side deduplication, incremental-only backups, and encrypted remote replication.

### Microsoft Hyper-V & Azure Stack HCI
Microsoft Hyper-V provides virtualization deeply integrated with Windows Server and Active Directory ecosystems:
- **Storage Spaces Direct (S2D):** Windows Server software-defined storage pooling NVMe, SSD, and HDD drives across cluster nodes using 3-way mirroring.
- **Licensing Model:** Windows Server Datacenter Edition provides unlimited Windows Server guest instances on licensed physical cores (minimum 16 cores per host).
- **Management:** Windows Admin Center (WAC) and System Center Virtual Machine Manager (SCVMM).

---

## 3. Architectural Migration Blockers & Pre-Flight Checks

### 1. Raw Device Mappings (RDMs)
- **Technical Mechanism:** An RDM maps a Fibre Channel or iSCSI storage LUN directly to a VM, bypassing the VMFS filesystem layer. RDMs can be configured in Virtual Compatibility Mode or Physical Compatibility Mode (Pass-Through).
- **Migration Impact:** Export utilities (`qemu-img`, `virt-v2v`, OVF Tool) only see the small pointer file (`.vmdk`), not the raw underlying SAN LUN data. Attempting to copy an RDM pointer results in an empty or unbootable target disk.
- **Resolution Path:**
  1. Convert RDM to a standard virtual disk within VMware before cutover:
     `vmkfstools -i "/vmfs/volumes/Datastore/vm/vm-rdm.vmdk" -d thin "/vmfs/volumes/Datastore/vm/vm-converted.vmdk"`
  2. Alternatively, present the target storage LUN directly to the destination hypervisor (e.g., via iSCSI or Ceph RBD) and attach the raw block volume.

### 2. Active & Stale Snapshots
- **Technical Mechanism:** Snapshots freeze the base virtual disk (`-flat.vmdk`) and redirect writes to delta differencing disks (`-000001-delta.vmdk`).
- **Migration Impact:**
  - Delta disks degrade storage IOPS substantially.
  - Large or nested snapshot trees frequently cause Change Block Tracking (CBT) synchronization failures and snapshot consolidation locks during cold and warm cutovers.
- **Resolution Path:**
  - Consolidate all snapshots in vCenter prior to initiating disk replication.
  - Delete snapshots older than 72 hours. Ensure zero delta disks exist during final cutover.

### 3. Shared Disks & Multi-Writer Flags
- **Technical Mechanism:** Clustered workloads (e.g., Microsoft Windows Server Failover Clustering with shared disks, Oracle Real Application Clusters - RAC) utilize `sharing: sharingMultiWriter` on SCSI controllers.
- **Migration Impact:** Standard hypervisor migration tools clone disks independently, severing cluster arbitration and causing split-brain or data corruption.
- **Resolution Path:**
  - Re-architect shared disks using destination-native shared block storage (e.g., Proxmox shared Ceph RBD with exclusive locks disabled, or Hyper-V Shared VHDX / VHD Set).
  - Alternatively, convert to application-level replication (e.g., Microsoft SQL Server Always On Availability Groups, Oracle Data Guard, PostgreSQL streaming replication) which eliminates shared disk requirements entirely.

### 4. Legacy Guest Operating Systems & VirtIO Driver Incompatibilities
- **Technical Mechanism:** VMware virtual hardware presents virtualized LSI Logic SAS, LSI Logic Parallel, BusLogic, or VMware Paravirtual SCSI (PVSCSI) controllers. Proxmox VE default storage controller is VirtIO SCSI, which provides near-native bus performance.
- **Migration Impact:**
  - Windows Server 2003, 2008, 2008 R2, and early Linux releases lack inbox VirtIO drivers.
  - Booting an unconverted Windows image on VirtIO SCSI results in Stop Error `0x0000007B` (`INACCESSIBLE_BOOT_DEVICE`).
- **Resolution Path:**
  - For Windows: Attach temporary VirtIO ISO (`virtio-win.iso`) and run driver injection, or initial boot using SATA/IDE controller on Proxmox, install VirtIO drivers, then switch boot disk to VirtIO SCSI.
  - Modern Linux (RHEL 7+, Debian 9+, Ubuntu 16.04+): Native VirtIO kernel modules (`virtio_pci`, `virtio_scsi`, `virtio_net`) are built into initramfs.

### 5. Massive / Monster VMs
- **Technical Mechanism:** Workloads provisioned with >32 vCPUs or >128 GB RAM spanning multiple physical CPU sockets (Non-Uniform Memory Access - NUMA).
- **Migration Impact:** Without explicit virtual NUMA (vNUMA) topology configuration, memory latency increases by 30% to 50% due to cross-socket inter-connect overhead.
- **Resolution Path:** Configure explicit NUMA sockets in Proxmox (`numa: 1`, `sockets: 2`, `cores: 16`) matching the target host physical topology.

---

## 4. Destination Cluster Sizing Calculations

### 1. vCPU to Physical Core Overcommit
- **Production Standard:** 2.0:1 (2 virtual CPUs per physical core).
- **Non-Production / VDI Standard:** 4.0:1 (4 virtual CPUs per physical core).
- **Hyper-Threading Factor:** Physical cores are calculated based on base cores, not hyper-threaded logical threads, to maintain predictable performance envelopes.

### 2. Memory Sizing & Hypervisor Overhead
- **Base Host Allocation:** 16 GB per host node for Linux OS and management daemons.
- **Ceph OSD Overhead:** 4 GB dedicated RAM per Ceph OSD drive daemon.
- **ZFS ARC Cache:** Up to 50% of host RAM or minimum 16 GB for ZFS ARC if local ZFS storage is utilized.
- **Guest VM Buffer:** 105% of assigned vRAM to account for QEMU virtualization overhead.

### 3. Storage Sizing & Resilience Factor
- **Raw VM Capacity in Use:** Sum of actual provisioned/consumed disk data.
- **Snapshot & Headroom Buffer:** Add 20% to accommodate snapshots and performance maintenance.
- **Ceph Storage Factor:** Usable storage $\times 3.0$ for standard 3x replication.
- **ZFS Storage Factor:** Usable storage $\times 1.33$ to $1.50$ depending on RAIDZ1/RAIDZ2 pool geometry.

### 4. High Availability (HA) Buffer
- **$N+1$ Architecture:** Cluster can sustain the failure of 1 physical host node without service degradation.
- **$N+2$ Architecture:** Cluster can sustain the failure of 2 physical host nodes simultaneously (mandatory for clusters $>8$ nodes or strict SLAs).

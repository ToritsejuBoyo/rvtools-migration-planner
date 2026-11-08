#!/usr/bin/env python3
"""
Media Generation Engine: rvtools-migration-planner

Produces high-definition terminal playback demo (assets/demo.mp4) and
animated web graphic (assets/demo.gif) demonstrating RVTools Excel
ingestion, blocker identification, 5-wave scheduling, and Ceph cluster sizing.

Adheres strictly to Workspace Rule 7 (Zero-Emoji Enterprise Tone) and
Rule 10 (Rich Media & Installation Guide).
"""

import os
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 720
BG_COLOR = (15, 23, 42)       # Slate navy
HEADER_BG = (30, 41, 59)
TEXT_COLOR = (241, 245, 249)
MUTED_TEXT = (148, 163, 184)
PROMPT_COLOR = (249, 115, 22)  # Proxmox Orange
CMD_COLOR = (255, 255, 255)
GREEN_COLOR = (52, 211, 153)
YELLOW_COLOR = (251, 191, 36)
RED_COLOR = (248, 113, 113)
BLUE_COLOR = (96, 165, 250)
CYAN_COLOR = (56, 189, 248)


def create_base_canvas():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Terminal top bar
    draw.rectangle([(0, 0), (WIDTH, 42)], fill=HEADER_BG)
    # Window control circles
    draw.ellipse([(16, 14), (28, 26)], fill=(239, 68, 68))
    draw.ellipse([(36, 14), (48, 26)], fill=(245, 158, 11))
    draw.ellipse([(56, 14), (68, 26)], fill=(16, 185, 129))

    # Title
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    draw.text(
        (WIDTH // 2 - 250, 12),
        "terminal - rvtools-migration-planner (VMware to Proxmox/Hyper-V Sizing Engine)",
        font=font,
        fill=MUTED_TEXT,
    )

    return img, draw


def render_frames(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("consola.ttf", 14)
        bold_font = ImageFont.truetype("consolab.ttf", 14)
        title_font = ImageFont.truetype("consolab.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
        bold_font = font
        title_font = font

    prompt = "admin@virt-triage:~$ "
    cmd = "python scripts/rvtools_planner.py -i tests/fixtures/fixture-enterprise-datacenter.xlsx --target proxmox --sanitize"

    screens = [
        # Frame 1: Empty prompt
        [
            (30, 65, prompt, PROMPT_COLOR, bold_font),
            (210, 65, "", CMD_COLOR, bold_font),
        ],
        # Frame 2: Command typed
        [
            (30, 65, prompt, PROMPT_COLOR, bold_font),
            (210, 65, cmd, CMD_COLOR, bold_font),
        ],
        # Frame 3: Ingestion & Telemetry
        [
            (30, 65, prompt, PROMPT_COLOR, bold_font),
            (210, 65, cmd, CMD_COLOR, bold_font),
            (30, 95, "[*] Reading RVTools Excel workbook: tests/fixtures/fixture-enterprise-datacenter.xlsx", BLUE_COLOR, font),
            (30, 115, "[+] Streaming OpenXML parser extracted: vInfo (100 rows), vDisk (215 rows), vSnapshot (18 rows)", GREEN_COLOR, font),
            (30, 135, "[+] Applied client-side SHA-256 sanitization on hostnames, datastores, and IPs.", GREEN_COLOR, font),
            (30, 160, "================================================================================", MUTED_TEXT, font),
            (30, 180, "VMWARE VSPHERE INVENTORY ASSESSMENT & MIGRATION READINESS REPORT", CYAN_COLOR, title_font),
            (30, 205, "================================================================================", MUTED_TEXT, font),
        ],
        # Frame 4: Metrics & Blockers
        [
            (30, 65, prompt, PROMPT_COLOR, bold_font),
            (210, 65, cmd, CMD_COLOR, bold_font),
            (30, 95, "[*] Reading RVTools Excel workbook: tests/fixtures/fixture-enterprise-datacenter.xlsx", BLUE_COLOR, font),
            (30, 115, "[+] Streaming OpenXML parser extracted: vInfo (100 rows), vDisk (215 rows), vSnapshot (18 rows)", GREEN_COLOR, font),
            (30, 135, "[+] Applied client-side SHA-256 sanitization on hostnames, datastores, and IPs.", GREEN_COLOR, font),
            (30, 160, "================================================================================", MUTED_TEXT, font),
            (30, 180, "VMWARE VSPHERE INVENTORY ASSESSMENT & MIGRATION READINESS REPORT", CYAN_COLOR, title_font),
            (30, 205, "================================================================================", MUTED_TEXT, font),
            (30, 225, "Estate Scope:     100 Total VMs (92 Active, 8 Powered-Off / Zombie Candidates)", TEXT_COLOR, font),
            (30, 245, "Compute Profile:  488 active vCPUs | 1,472.0 GB active vRAM | 2,987.0 GB in-use Storage", TEXT_COLOR, font),
            (30, 265, "Readiness Score:  81.0% Migration Ready (19 VMs require architectural remediation)", YELLOW_COLOR, bold_font),
            (30, 295, "CRITICAL BLOCKERS DETECTED (ACTION REQUIRED PRIOR TO CUTOVER):", RED_COLOR, bold_font),
            (30, 315, "  [CRITICAL] Raw Device Mappings: 2 Physical/Virtual RDMs (vm-0042, vm-0089) -> v2v required", RED_COLOR, font),
            (30, 335, "  [CRITICAL] Stale Snapshots:     3 Snapshots >72h / >20GB (vm-0012, vm-0055) -> consolidate", RED_COLOR, font),
            (30, 355, "  [CRITICAL] Multi-Writer Disks:  2 Clustered Oracle RAC disks -> shared Ceph RBD / app sync", RED_COLOR, font),
            (30, 375, "  [WARNING]  Legacy Guest OS:     4 Windows 2003/2008 & CentOS 5 VMs -> offline VirtIO inject", YELLOW_COLOR, font),
            (30, 395, "  [WARNING]  Monster VM Topology: 1 SAP HANA Node (64 vCPU, 256GB RAM) -> explicit vNUMA pin", YELLOW_COLOR, font),
        ],
        # Frame 5: Waves & Sizing Plan
        [
            (30, 65, prompt, PROMPT_COLOR, bold_font),
            (210, 65, cmd, CMD_COLOR, bold_font),
            (30, 95, "CRITICAL BLOCKERS DETECTED (ACTION REQUIRED PRIOR TO CUTOVER):", RED_COLOR, bold_font),
            (30, 115, "  [CRITICAL] Raw Device Mappings: 2 Physical/Virtual RDMs (vm-0042, vm-0089) -> v2v required", RED_COLOR, font),
            (30, 135, "  [CRITICAL] Stale Snapshots:     3 Snapshots >72h / >20GB (vm-0012, vm-0055) -> consolidate", RED_COLOR, font),
            (30, 155, "  [CRITICAL] Multi-Writer Disks:  2 Clustered Oracle RAC disks -> shared Ceph RBD / app sync", RED_COLOR, font),
            (30, 180, "PHASED MIGRATION WAVE SCHEDULE:", BLUE_COLOR, bold_font),
            (30, 200, "  Wave 0 (Decommission):  8 VMs (Reclaims 412.0 GB storage capacity)", MUTED_TEXT, font),
            (30, 220, "  Wave 1 (Pilot):        24 VMs (Stateless dev/test Linux workloads)", GREEN_COLOR, font),
            (30, 240, "  Wave 2 (Tier-2 Apps):  38 VMs (Internal web apps, build agents, analytics)", TEXT_COLOR, font),
            (30, 260, "  Wave 3 (Tier-1 Core):  18 VMs (Standalone SQL Server, ERP core, domain controllers)", YELLOW_COLOR, font),
            (30, 280, "  Wave 4 (High-Risk):    12 VMs (Clustered Oracle RAC, RDM workloads, Monster VMs)", RED_COLOR, font),
            (30, 310, "TARGET DESTINATION CLUSTER SIZING (PROXMOX VE WITH CEPH 3X REPLICATION):", CYAN_COLOR, bold_font),
            (30, 330, "  Hardware Profile:      64 Cores per Node | 512 GB RAM per Node", TEXT_COLOR, font),
            (30, 350, "  Physical Compute Req:  244 Physical Cores (2.0:1 overcommit on active vCPUs)", TEXT_COLOR, font),
            (30, 370, "  Physical Memory Req:   1,701.0 GB Host RAM (1.05 vRAM + 10% ZFS/Hypervisor overhead)", TEXT_COLOR, font),
            (30, 390, "  Storage Sizing:        3.5 TB Usable Pool | 10.5 TB Raw NVMe (Ceph 3x + 20% headroom)", TEXT_COLOR, font),
            (30, 410, "  Cluster Topology:      4 Nodes (N+0 Baseline) -> 5 Nodes Recommended (N+1 Resilience)", GREEN_COLOR, bold_font),
            (30, 440, "[+] Full Markdown and JSON assessment exported to: ./rvtools-migration-report.md", GREEN_COLOR, font),
            (30, 465, prompt, PROMPT_COLOR, bold_font),
        ]
    ]

    # Durations per screen in frames (at 4 fps)
    durations = [3, 4, 6, 9, 12]
    frame_idx = 0

    for screen_idx, elements in enumerate(screens):
        count = durations[screen_idx]
        for _ in range(count):
            img, draw = create_base_canvas()
            for elem in elements:
                x, y, text, color, f = elem
                draw.text((x, y), text, font=f, fill=color)
            out_file = output_dir / f"frame_{frame_idx:04d}.png"
            img.save(out_file)
            frame_idx += 1

    return frame_idx


def generate_mp4(frames_dir: Path, output_mp4: Path):
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "4",
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-profile:v", "high",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output_mp4)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def generate_gif(frames_dir: Path, output_gif: Path):
    palette_path = frames_dir / "palette.png"
    cmd_palette = [
        "ffmpeg", "-y",
        "-framerate", "4",
        "-i", str(frames_dir / "frame_%04d.png"),
        "-vf", "fps=4,scale=1200:-1:flags=lanczos,palettegen=stats_mode=diff",
        str(palette_path)
    ]
    subprocess.run(cmd_palette, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    cmd_gif = [
        "ffmpeg", "-y",
        "-framerate", "4",
        "-i", str(frames_dir / "frame_%04d.png"),
        "-i", str(palette_path),
        "-lavfi", "fps=4,scale=1200:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3",
        str(output_gif)
    ]
    subprocess.run(cmd_gif, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    repo_root = Path(__file__).resolve().parent.parent
    assets_dir = repo_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = assets_dir / "frames"

    print("[*] Rendering terminal demo animation frames...")
    total_frames = render_frames(frames_dir)
    print(f"[+] Rendered {total_frames} frames.")

    mp4_path = assets_dir / "demo.mp4"
    gif_path = assets_dir / "demo.gif"

    print("[*] Compiling HD video (assets/demo.mp4)...")
    generate_mp4(frames_dir, mp4_path)
    print(f"[+] Generated: {mp4_path} ({mp4_path.stat().st_size / 1024:.1f} KB)")

    print("[*] Compiling animated GIF (assets/demo.gif)...")
    generate_gif(frames_dir, gif_path)
    print(f"[+] Generated: {gif_path} ({gif_path.stat().st_size / 1024:.1f} KB)")

    # Clean up intermediate frames
    for f in frames_dir.glob("*.png"):
        f.unlink()
    frames_dir.rmdir()
    print("[+] Cleaned up temporary rendering frames.")


if __name__ == "__main__":
    main()

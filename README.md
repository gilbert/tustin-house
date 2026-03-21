# Tustin House NAS

Home NAS server.

## Hardware

- Motherboard: Gigabyte B550M DS3H AC R2 (AM4, Micro-ATX)
- CPU: AMD Ryzen 7 5800XT (AM4, 8-core/16-thread, no iGPU)
- RAM: G.Skill Ripjaws V 16GB (2×8GB) DDR4-3200 CL16
- Boot drive: [brand/model of your 256GB NVMe] in M.2 slot
- Case: Fractal Design Node 804 (Micro-ATX cube, 8×3.5" bays)
- PSU: be quiet! Pure Power 13 M 650W (ATX, fully modular, 80+ Gold)
- Data drive slot 1: WD Red Pro 10TB (WD103KFBX) — SATA port 1
- OS: OpenMediaVault 8 "Synchrony" (Debian-based)

PCIe x16 slot is empty and reserved — if display output is ever needed (e.g. for troubleshooting without SSH), a cheap GPU can be temporarily dropped in there.

### Upgrade path for more drives:

The board has 4 native SATA ports, all usable right now.

When you hit drive 5, add a PCIe SATA expansion card (e.g. IOCrest SI-PEX40064, ASM1064 chip, ~$25) into the PCIe x1 slot. This adds 4 more ports for a total of 8, which is the Node 804's maximum capacity. No reinstall or BIOS changes needed — Linux detects it automatically.

SATA expansion card: IOCrest SI-PEX40064 (PCIe x1 slot) — drives 5–8 connect here

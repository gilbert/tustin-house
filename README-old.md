# Tustin House NAS

Home NAS server built on a Raspberry Pi 5.

## Hardware

- **Board:** Raspberry Pi 5 Model B (16GB RAM)
- **Storage:** 32GB SD card (boot/OS) + WD Red Pro 10TB 3.5" HDD (not yet configured)
- **SATA HAT:** Radxa Penta SATA HAT (Amazon B0DX1HQWB2) — requires PCIe config (not yet set up)
- **Network:** Gigabit Ethernet (interface: `end0`)

## Software

- **OS:** Debian GNU/Linux 13 (trixie) / Raspberry Pi OS
- **NAS Platform:** OpenMediaVault (installed via community script)
- **Network Stack:** systemd-networkd + netplan (NetworkManager removed by OMV)
- **mDNS:** Avahi — accessible at `tustinhouse.local`
- **Docker:** Docker 29.2.1 + Compose 5.1.0
- **Tailscale:** VPN for remote access (Tailscale IP: `100.96.189.73`, SSH enabled)

## Services

### Immich (Photo/Video Backup)
Self-hosted Google Photos replacement.
- **Web UI:** http://tustinhouse.local:2283
- **Config:** `/opt/immich/docker-compose.yml` and `/opt/immich/.env`
- **Storage:** `/opt/immich/library` (SD card — migrate to SATA drive later)
- **Database:** `/opt/immich/postgres`
- **iOS app:** Connect to `http://tustinhouse.local:2283` (local) or `http://100.96.189.73:2283` (remote via Tailscale)
- **Features:** AI face/object recognition, timeline, maps, memories

## Access

### Local
- **OMV Web UI:** http://tustinhouse.local
- **Immich:** http://tustinhouse.local:2283
- **SSH:** `ssh troot@tustinhouse.local`

### Remote (via Tailscale)
- **OMV Web UI:** http://100.96.189.73
- **Immich:** http://100.96.189.73:2283
- **SSH:** `ssh troot@tustinhouse`

## Known Issues

- OMV identifies the ethernet interface as `eth0`, but the Pi 5 uses `end0`. When OMV regenerates configs, verify that netplan (`/etc/netplan/*.yaml`) and avahi (`/etc/avahi/avahi-daemon.conf`) reference `end0`, not `eth0`. The OMV interface has been updated to match on `end0` but the netplan key still says `eth0`.

## Next Steps

### 1. Configure SATA Drive
- Enable PCIe in `/boot/firmware/config.txt` for the Radxa Penta SATA HAT
- Create filesystem on WD Red Pro 10TB via OMV
- Migrate Immich storage from SD card to SATA drive
- Set up shared folders and SMB/CIFS shares

## Future Features

### Cryptomator (Encrypted Vault)
Encrypted file vault for sensitive documents (subset of files, not whole-drive encryption).
- Creates encrypted vaults within regular folders on the NAS
- iOS app for accessing encrypted files on the go
- Runs alongside Immich — Immich for photos/videos, Cryptomator for sensitive documents

### Additional Ideas
- Automated backups
- UPS monitoring for safe shutdown

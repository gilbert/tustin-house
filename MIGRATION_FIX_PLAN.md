# Storage Migration Fix Plan

## The Problem

Immich reports only ~220 GB of available storage instead of the expected ~9 TB. All `/sharedfolders/` paths are plain directories on the 238 GB NVMe boot drive (`/dev/nvme0n1p2`), not the 10 TB WD Red Pro HDD (`/dev/sda1`).

OMV's web UI shows the shared folders assigned to the HDD — the XML config maps every shared folder to the HDD's `mntentref`. However, **OMV's `/sharedfolders/` bind mount feature has been disabled by default since OMV 5.3.3** (`OMV_SHAREDFOLDERS_DIR_ENABLED="NO"` in `/etc/default/openmediavault`). This means no bind mounts are created regardless of whether "Apply" is clicked. The feature was disabled because systemd mount units conflict with Docker — containers hold the mounts open, preventing Salt from restarting them during config changes.

The HDD is mounted at `/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac` but only has empty directories created by OMV.

### Why not re-enable bind mounts?

Enabling `OMV_SHAREDFOLDERS_DIR_ENABLED="YES"` is officially unsupported for Docker workloads. It would also require reassigning `dev-compose` and `dev-compose-data` to the NVMe filesystem first (which OMV may refuse since it's the boot drive). Instead, the fix is simpler: **create symlinks for each drive and update compose volume paths to use them directly.**

## Requirements

1. **Bulk user data must live on the 10 TB HDD** — media libraries, Immich photo/video uploads, Seafile user documents.
2. **Service configs and databases must stay on the NVMe boot drive** — Authentik (postgres, config), NPM (proxy config, SSL certs), Immich (postgres), Seafile (MariaDB), Jellyfin (config/cache). These are small, benefit from SSD speed, and if the HDD fails, service configs survive.
3. **Compose files and landing page stay on NVMe** — they are infrastructure, not user data.

## Current State

### Drives

| Device | Size | Symlink | Mount Point | Role |
|---|---|---|---|---|
| `/dev/nvme0n1p2` | 221 GB | — | `/` | Boot drive (NVMe SSD) |
| `/dev/sda1` | 9.1 TB | `/hdd-almond-10tb` (to create) | `/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac` | Data drive (WD Red Pro), currently empty |
| `/dev/sdb` | 931 GB | `/hdd-bread-1tb` (to create) | not mounted | Old Windows drive (WD Blue), not yet formatted for OMV |

### Services Running

| Service | Status | Data Location | Needs Migration? |
|---|---|---|---|
| Authentik | Running | NVMe (`/sharedfolders/dev/compose/authentik/`) | No |
| NPM | Running | NVMe (`/sharedfolders/dev/compose/nginx-proxy-manager/`) | No |
| Cloudflared | Running | No volumes | No |
| Landing page | Running | NVMe (`/sharedfolders/compose/landing-page/`) | No |
| Immich | **Stopped** | NVMe (`/sharedfolders/compose-data/immich/`) — 3.1 GB | **Yes** (uploads to HDD) |
| Jellyfin | **Stopped** | NVMe (`/sharedfolders/`) — media dirs empty | **Yes** (media paths to HDD) |
| Seafile | **Stopped** | NVMe (`/sharedfolders/dev/compose-data/seafile/`) | **Yes** (data to HDD) |

### Data to Move

| Path on NVMe | Size | Destination on HDD |
|---|---|---|
| `/sharedfolders/compose-data/immich/upload/` | 2.8 GB | `/hdd-almond-10tb/immich/` |
| `/sharedfolders/dev/compose-data/seafile/data/` | ~200 MB | `/hdd-almond-10tb/seafile/` |
| `/sharedfolders/{movies,tv,music,photos,videos}/` | empty | `/hdd-almond-10tb/{movies,tv,music,photos,videos}/` |

---

## Migration Steps

### Step 1 — Create drive symlinks

```bash
ln -s /srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac /hdd-almond-10tb
# /hdd-bread-1tb will be created later when the 1TB drive is formatted for OMV
```

Verify:

```bash
ls -la /hdd-almond-10tb/
# Should show the HDD contents (empty dirs: movies, tv, music, photos, etc.)
```

### Step 2 — Create HDD directories for service data

```bash
mkdir -p /hdd-almond-10tb/immich
mkdir -p /hdd-almond-10tb/seafile
```

The media directories (`movies`, `tv`, `music`, `photos`, `videos`, `documents`) already exist on the HDD from OMV's shared folder creation.

### Step 3 — Copy data to the HDD

Immich and Seafile are already stopped. Copy their user data:

```bash
# Immich uploads (2.8 GB)
rsync -aP /sharedfolders/compose-data/immich/upload/ /hdd-almond-10tb/immich/

# Seafile user files
rsync -aP /sharedfolders/dev/compose-data/seafile/data/ /hdd-almond-10tb/seafile/
```

Media directories (`movies`, `tv`, etc.) are empty on the NVMe — nothing to copy.

### Step 4 — Fix permissions

```bash
# Immich server runs as UID 1000
chown -R 1000:1000 /hdd-almond-10tb/immich
```

### Step 5 — Update compose YAML in OMV UI

All compose files are managed by the OMV compose plugin (Storage → Compose → Files). Edit each service's YAML in the OMV web UI:

**Immich** — change the upload volume:

```yaml
# Before:
- /sharedfolders/compose-data/immich/upload:/data

# After:
- /hdd-almond-10tb/immich:/data
```

Postgres volume stays unchanged (`/sharedfolders/compose-data/immich/postgres` — plain dir on NVMe).

Also change `DB_STORAGE_TYPE` from `HDD` to `SSD` since postgres is on the NVMe:

```yaml
# Before:
- DB_STORAGE_TYPE=HDD

# After:
- DB_STORAGE_TYPE=SSD
```

**Jellyfin** — change media volumes:

```yaml
# Before:
- /sharedfolders/movies:/media/movies
- /sharedfolders/tv:/media/tv
- /sharedfolders/music:/media/music
- /sharedfolders/photos:/media/photos
- /sharedfolders/videos:/media/videos

# After:
- /hdd-almond-10tb/movies:/media/movies
- /hdd-almond-10tb/tv:/media/tv
- /hdd-almond-10tb/music:/media/music
- /hdd-almond-10tb/photos:/media/photos
- /hdd-almond-10tb/videos:/media/videos
```

Config and cache volumes stay unchanged (`/sharedfolders/dev/config/jellyfin`, `/sharedfolders/dev/cache/jellyfin` — NVMe).

**Seafile** — change the data volume:

```yaml
# Before:
- /sharedfolders/dev/compose-data/seafile/data:/shared

# After:
- /hdd-almond-10tb/seafile:/shared
```

MariaDB volume stays unchanged (`/sharedfolders/dev/compose-data/seafile/db` — NVMe).

Also update the notification-server log volume:

```yaml
# Before:
- /sharedfolders/dev/compose-data/seafile/data/seafile/logs:/shared/seafile/logs

# After:
- /hdd-almond-10tb/seafile/seafile/logs:/shared/seafile/logs
```

**No changes needed** for Authentik, NPM, Cloudflared, or Landing page — their data stays on NVMe.

### Step 6 — Deploy and start services

In the OMV web UI, click the **Apply** button (or the ↑ up arrow next to each compose file) to regenerate the compose files with updated YAML, then start the services:

```bash
# Start Immich
cd /hdd-almond-10tb/dev/compose/immich && docker compose up -d

# Start Jellyfin
cd /hdd-almond-10tb/dev/compose/jellyfish && docker compose up -d

# Start Seafile
cd /hdd-almond-10tb/dev/compose/seafile && docker compose up -d
```

Or use the OMV Compose UI to start each service.

### Step 7 — Verify

```bash
# Immich should see ~9 TB
docker exec immich-server df -h /data
# Should show /dev/sda1 with 9.1T

# Jellyfin media should point to HDD
docker exec jellyfin df -h /media/movies
# Should show /dev/sda1

# Seafile data should point to HDD
docker exec seafile df -h /shared
# Should show /dev/sda1
```

Also check the web UIs:
- **Immich** (photos.tustin.house) — should show ~9 TB available, existing photos intact
- **Jellyfin** — media libraries accessible (currently empty, that's fine)
- **Seafile** — existing libraries and files present

### Step 8 — Clean up old NVMe data (after verification)

Once everything is confirmed working, remove the stale copies from the NVMe to reclaim space:

```bash
# Old Immich uploads (now at /hdd-almond-10tb/immich/)
rm -rf /sharedfolders/compose-data/immich/upload

# Old Seafile data (now at /hdd-almond-10tb/seafile/)
rm -rf /sharedfolders/dev/compose-data/seafile/data

# Empty media dirs on NVMe (Jellyfin now reads from HDD)
rm -rf /sharedfolders/movies /sharedfolders/music /sharedfolders/photos
rm -rf /sharedfolders/tv /sharedfolders/videos
```

Do **not** remove:
- `/sharedfolders/compose-data/immich/postgres` — active Immich database on NVMe
- `/sharedfolders/dev/compose-data/seafile/db` — active Seafile database on NVMe
- `/sharedfolders/dev/compose/` — service configs on NVMe
- `/sharedfolders/compose/` — compose infrastructure on NVMe

---

## Final State

| Data | Drive | Path |
|---|---|---|
| Immich photo/video uploads | HDD (9.1 TB) | `/hdd-almond-10tb/immich/` |
| Seafile user documents | HDD (9.1 TB) | `/hdd-almond-10tb/seafile/` |
| Movies, TV, Music, Photos, Videos | HDD (9.1 TB) | `/hdd-almond-10tb/{movies,tv,music,photos,videos}/` |
| Immich postgres DB | NVMe (221 GB) | `/sharedfolders/compose-data/immich/postgres/` |
| Seafile MariaDB | NVMe (221 GB) | `/sharedfolders/dev/compose-data/seafile/db/` |
| Authentik (postgres, config) | NVMe (221 GB) | `/sharedfolders/dev/compose/authentik/` |
| NPM (config, certs) | NVMe (221 GB) | `/sharedfolders/dev/compose/nginx-proxy-manager/` |
| Jellyfin config/cache | NVMe (221 GB) | `/sharedfolders/dev/{config,cache}/jellyfin/` |
| Compose files | NVMe (221 GB) | `/sharedfolders/compose/` |
| Landing page | NVMe (221 GB) | `/sharedfolders/compose/landing-page/` |

## Future: 1TB Drive (hdd-bread-1tb)

`/dev/sdb` is a 931 GB WD Blue with old Windows partitions (NTFS). To use it:

1. Wipe and format it in OMV UI → Storage → Disks → select sdb → Wipe, then Storage → File Systems → Create (ext4)
2. Mount it in OMV
3. Create the symlink: `ln -s /srv/dev-disk-by-uuid-<new-uuid> /hdd-bread-1tb`

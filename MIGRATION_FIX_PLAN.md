# Storage Migration Fix Plan

## The Problem

Immich reports only ~220 GB of available storage instead of the expected ~9 TB. Investigation revealed that **all** `/sharedfolders/` paths are sitting on the 238 GB NVMe boot drive (`/dev/nvme0n1p2`), not the 10 TB WD Red Pro HDD (`/dev/sda1`).

OMV's web UI shows the shared folders correctly assigned to the HDD — the XML config (`/etc/openmediavault/config.xml`) maps every shared folder to the HDD's `mntentref`. However, the corresponding **bind mount entries were never written to `/etc/fstab`**. Without bind mounts, `/sharedfolders/*` are just plain directories on the NVMe root filesystem. The HDD is mounted at `/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac` but has empty directories — nothing is using it.

## Requirements

1. **Bulk user data must live on the 10 TB HDD** — media libraries, Immich photo/video uploads, Seafile user documents.
2. **Service configs and databases must stay on the NVMe boot drive** — Authentik (postgres, config), NPM (proxy config, SSL certs), Immich (postgres), Seafile (MariaDB), Jellyfin (config/cache). These are small, benefit from SSD speed, and critically: if the HDD is swapped out or fails, service configs and databases survive.
3. **Compose files and landing page stay on NVMe** — they are infrastructure, not user data.

## Current State

### Drives

| Device | Size | Mount Point | Role |
|---|---|---|---|
| `/dev/nvme0n1p2` | 221 GB | `/` | Boot drive (NVMe SSD) |
| `/dev/sda1` | 9.1 TB | `/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac` | Data drive (WD Red Pro HDD), currently empty |

### OMV Shared Folders (from config.xml)

All share the same `mntentref` pointing to `/dev/sda1`:

| OMV Name | Relative Path | Should Be On |
|---|---|---|
| `movies` | `movies/` | HDD |
| `tv` | `tv/` | HDD |
| `music` | `music/` | HDD |
| `photos` | `photos/` | HDD |
| `videos` | `videos/` | HDD |
| `documents` | `documents/` | HDD |
| `dev-compose` | `dev/compose/` | **NVMe** (service configs) |
| `dev-compose-data` | `dev/compose-data/` | **NVMe** (databases) |

Note: `/sharedfolders/compose/` and `/sharedfolders/compose-data/` also exist as plain directories on the NVMe but are **not** OMV shared folders — they were created manually and will remain on the NVMe as-is.

### Volume Paths by Service

**Jellyfin:**
- `/sharedfolders/dev/config/jellyfin:/config` — config, stay on NVMe
- `/sharedfolders/dev/cache/jellyfin:/cache` — cache, stay on NVMe
- `/sharedfolders/movies:/media/movies` — media, move to HDD
- `/sharedfolders/tv:/media/tv` — media, move to HDD
- `/sharedfolders/music:/media/music` — media, move to HDD
- `/sharedfolders/photos:/media/photos` — media, move to HDD
- `/sharedfolders/videos:/media/videos` — media, move to HDD

**Immich:**
- `/sharedfolders/compose-data/immich/upload:/data` — user uploads, move to HDD
- `/sharedfolders/compose-data/immich/postgres:/var/lib/postgresql/data` — database, stay on NVMe

**Seafile:**
- `/sharedfolders/dev/compose-data/seafile/data:/shared` — mixed config+user files, move to HDD
- `/sharedfolders/dev/compose-data/seafile/db:/var/lib/mysql` — database, stay on NVMe

**Authentik:** all volumes under `/sharedfolders/dev/compose/authentik/` — stay on NVMe

**NPM:** all volumes under `/sharedfolders/dev/compose/nginx-proxy-manager/` — stay on NVMe

**Cloudflared:** no volumes

**Landing page:** `/sharedfolders/compose/landing-page` — stay on NVMe

---

## Migration Steps

### Step 1 — OMV UI: Reassign dev folders to NVMe

In OMV web UI → Storage → Shared Folders:

- Edit **`dev-compose`** — change filesystem from HDD to NVMe
- Edit **`dev-compose-data`** — change filesystem from HDD to NVMe

**Do NOT click Apply yet.** We need to move data to the HDD first, because applying will create bind mounts that hide the current NVMe data behind empty HDD directories.

### Step 2 — Stop services that write user data

```bash
docker stop jellyfin immich-server immich-machine-learning immich-postgres immich-redis \
  seafile seafile-mysql seafile-redis seafile-notification-server
```

NPM, Authentik, cloudflared, and the landing page can keep running — their data stays on the NVMe.

### Step 3 — Copy media data to the HDD

```bash
HDD=/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac

# Media libraries (used by Jellyfin)
rsync -aP /sharedfolders/movies/   $HDD/movies/
rsync -aP /sharedfolders/tv/       $HDD/tv/
rsync -aP /sharedfolders/music/    $HDD/music/
rsync -aP /sharedfolders/photos/   $HDD/photos/
rsync -aP /sharedfolders/videos/   $HDD/videos/

# Seafile user files — moving to "documents" shared folder on HDD
rsync -aP /sharedfolders/dev/compose-data/seafile/data/ $HDD/documents/seafile/
```

### Step 4 — Deploy the bind mounts

Click **Apply** in the OMV web UI, or run:

```bash
omv-salt deploy run fstab
systemctl daemon-reload
mount -a
```

Verify the media folders now point to the HDD:

```bash
df -h /sharedfolders/movies /sharedfolders/documents
```

Both should show `/dev/sda1` with ~9.1T available.

Also verify the dev folders stayed on NVMe:

```bash
df -h /sharedfolders/dev/compose /sharedfolders/dev/compose-data
```

Should show `/dev/nvme0n1p2`.

### Step 5 — Update compose files for new paths

**Immich** — change the upload volume to use the HDD-backed `photos` shared folder.

In the Immich compose file, change:
```yaml
- /sharedfolders/compose-data/immich/upload:/data
```
to:
```yaml
- /sharedfolders/photos/immich:/data
```

Then move the existing uploads:
```bash
rsync -aP /sharedfolders/compose-data/immich/upload/ /sharedfolders/photos/immich/
```

The Immich postgres volume (`/sharedfolders/compose-data/immich/postgres`) is unchanged — it remains a plain directory on the NVMe.

**Seafile** — change the data volume to use the HDD-backed `documents` shared folder.

In the Seafile compose file, change:
```yaml
- /sharedfolders/dev/compose-data/seafile/data:/shared
```
to:
```yaml
- /sharedfolders/documents/seafile:/shared
```

The data was already copied to this location in Step 3. The Seafile MariaDB volume (`/sharedfolders/dev/compose-data/seafile/db`) is unchanged — it stays on the NVMe.

### Step 6 — Fix permissions and restart

```bash
# Immich runs as UID 1000
chown -R 1000:1000 /sharedfolders/photos/immich

# Restart stopped services
docker start immich-redis immich-postgres
docker start immich-server immich-machine-learning
docker start seafile-redis seafile-mysql
docker start seafile seafile-notification-server
docker start jellyfin
```

### Step 7 — Verify

- Immich web UI should show ~9 TB available storage
- Seafile should show existing libraries and files
- Jellyfin media libraries should still be accessible
- All other services (Authentik, NPM, cloudflared, landing) should be unaffected

### Step 8 — Clean up old NVMe data (optional, after verification)

Once everything is confirmed working, the old copies on the NVMe can be removed to reclaim space:

```bash
# Old media library data (now served via HDD bind mounts)
# These directories are hidden behind bind mounts, so unmount first to access:
#   umount /sharedfolders/movies && rm -rf /sharedfolders/movies/* && mount -a
# Repeat for tv, music, photos, videos

# Old Immich uploads (replaced by new path)
rm -rf /sharedfolders/compose-data/immich/upload

# Old Seafile data (replaced by new path)
rm -rf /sharedfolders/dev/compose-data/seafile/data
```

---

## Final State

| Data | Drive | Path |
|---|---|---|
| Movies, TV, Music, Photos, Videos | HDD (9.1 TB) | `/sharedfolders/{movies,tv,music,photos,videos}/` |
| Immich photo/video uploads | HDD (9.1 TB) | `/sharedfolders/photos/immich/` |
| Seafile user documents | HDD (9.1 TB) | `/sharedfolders/documents/seafile/` |
| Immich postgres DB | NVMe (221 GB) | `/sharedfolders/compose-data/immich/postgres` |
| Seafile MariaDB | NVMe (221 GB) | `/sharedfolders/dev/compose-data/seafile/db` |
| Authentik (postgres, config) | NVMe (221 GB) | `/sharedfolders/dev/compose/authentik/` |
| NPM (config, certs) | NVMe (221 GB) | `/sharedfolders/dev/compose/nginx-proxy-manager/` |
| Jellyfin config/cache | NVMe (221 GB) | `/sharedfolders/dev/config/jellyfin/`, `/sharedfolders/dev/cache/jellyfin/` |
| Compose files | NVMe (221 GB) | `/sharedfolders/compose/` |
| Landing page | NVMe (221 GB) | `/sharedfolders/compose/landing-page/` |

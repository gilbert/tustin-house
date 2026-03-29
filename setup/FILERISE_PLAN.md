# FileRise — Web Upload UI for Jellyfin Media

## Problem Statement

Multiple users share a NAS running Jellyfin (media streaming) and Seafile (file storage). Users need to:

1. Upload videos/music that appear in Jellyfin for everyone
2. Control who can upload/delete in each media category (movies, TV, music, etc.)
3. Do all of this through a simple web UI (non-technical users)

Jellyfin has no upload feature — it scans media from filesystem directories. Users need a way to get files into those directories without SSH, SCP, or any command-line tools.

## Why Not seaf-fuse?

The original plan (`SEAFILE_ADD_FUSE.md`) proposed using Seafile's built-in FUSE mount to expose Seafile libraries as plain directories for Jellyfin. This works but is over-engineered for the problem:

- **Unnecessary round-trip**: Files uploaded to Seafile are chunked/encrypted into internal storage, then seaf-fuse reconstructs them on every read. For media that only needs to be written once and read many times, this adds overhead for no benefit.
- **Privileged container**: seaf-fuse requires `privileged: true` + `/dev/fuse` — a significant security surface increase.
- **Fragile startup**: seaf-fuse doesn't auto-start. Requires a cron job to poll every minute and restart it after container restarts.
- **Read-only**: seaf-fuse provides no write access, so Jellyfin can't create metadata sidecars. (Acceptable but not ideal.)
- **UUID-prefixed paths**: Library directories include Seafile's internal UUIDs, requiring a symlink layer to give Jellyfin stable paths.

The core insight: the actual need is "web UI that writes files to a directory." Seafile is a sync/collaboration platform — using it as a file upload proxy adds layers of abstraction that don't serve the use case.

## Chosen Solution: FileRise

[FileRise](https://github.com/error311/FileRise) is a lightweight, self-hosted web file manager (PHP + Apache) with:

- **Per-folder ACLs**: Independently toggle View, Upload, Create, Edit, Rename, Move, Copy, Delete, Extract, Share — per user, per folder.
- **Native OIDC**: Explicit Authentik support with auto-user-creation on first SSO login and IdP group → admin role mapping.
- **Direct filesystem writes**: Files land exactly where they're uploaded. No internal storage format, no database. Jellyfin reads the same files.
- **No database**: All state stored in flat files (JSON/txt). One fewer service to maintain and back up.
- **Docker-native**: Official image with PUID/PGID remapping.

### How it works

```
User                    FileRise              Filesystem           Jellyfin
(web browser)  ──────>  (web UI)  ──────>  /hdd-almond-10tb/  <──  (reads media)
                                           media/{movies,tv,...}
```

Files uploaded through FileRise's web UI are written directly to the filesystem. Jellyfin's library scan picks them up. No intermediate storage format, no FUSE, no reconstruction.

### Privacy / permission model

| Role | Access | How |
|------|--------|-----|
| **Admin** | Full access to all media folders, user management | FileRise admin + Authentik `filerise-admins` group |
| **Uploader** | Upload + view in specific folders (e.g., Movies, TV) | FileRise per-folder ACLs set by admin |
| **Viewer** | Browse and download only, no upload/delete | FileRise ACLs: View (all) + Download only |

ACLs are managed through FileRise's admin panel (Admin → Folder Access). Authentik handles authentication; FileRise handles authorization per folder.

## Implementation

### 1. Reorganize media directories

Currently, Jellyfin reads from top-level HDD directories:

```
/hdd-almond-10tb/movies
/hdd-almond-10tb/tv
/hdd-almond-10tb/music
/hdd-almond-10tb/photos
/hdd-almond-10tb/videos
```

FileRise expects a single upload root with subdirectories. Create a parent directory and move the existing media into it:

```bash
sudo mkdir -p /hdd-almond-10tb/media
sudo mv /hdd-almond-10tb/movies /hdd-almond-10tb/media/
sudo mv /hdd-almond-10tb/tv /hdd-almond-10tb/media/
sudo mv /hdd-almond-10tb/music /hdd-almond-10tb/media/
sudo mv /hdd-almond-10tb/photos /hdd-almond-10tb/media/
sudo mv /hdd-almond-10tb/videos /hdd-almond-10tb/media/
```

> **Note:** These are renames on the same filesystem — instant regardless of data size. No data is copied.

Check the current ownership first and note the UID/GID:

```bash
ls -ln /hdd-almond-10tb/media/
```

### 2. FileRise compose file

Create `/sharedfolders/compose/filerise/docker-compose.yml`:

```yaml
# FileRise — web file manager for Jellyfin media uploads
# Ref: https://github.com/error311/FileRise

services:
  filerise:
    image: error311/filerise-docker:latest
    container_name: filerise
    restart: unless-stopped
    ports:
      - "8090:80"
    environment:
      # ── Locale ──
      - TIMEZONE=America/Los_Angeles
      - DATE_TIME_FORMAT=m/d/y  h:iA
      # ── Uploads ──
      - TOTAL_UPLOAD_SIZE=10G
      # ── Reverse proxy ──
      - SECURE=true
      - FR_PUBLISHED_URL=https://files.tustin.house
      - FR_TRUSTED_PROXIES=127.0.0.1,172.16.0.0/12,10.0.0.0/8
      - FR_IP_HEADER=X-Forwarded-For
      # ── Permissions ──
      - PUID=YOUR_UID
      - PGID=YOUR_GID
      - CHOWN_ON_START=false
      - SCAN_ON_START=false
      # ── OIDC (Authentik) ──
      - FR_OIDC_AUTO_CREATE=true
      - FR_OIDC_GROUP_CLAIM=groups
      - FR_OIDC_ADMIN_GROUP=filerise-admins
      - FR_OIDC_EXTRA_SCOPES=groups
    volumes:
      - /hdd-almond-10tb/media:/var/www/uploads
      - /sharedfolders/dev/config/filerise/users:/var/www/users
      - /sharedfolders/dev/config/filerise/metadata:/var/www/metadata
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost/ || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

Key decisions:

- **Port 8090** — avoids conflicts with existing services (8080=Seafile, 8083=Seafile notifications, 8096=Jellyfin, 9000=Authentik, 2283=Immich).
- **No dedicated network** — FileRise has no database or sidecar services. A published port on the default bridge is sufficient (same pattern as Jellyfin but without `network_mode: host` since we don't need multiple ports).
- **`CHOWN_ON_START=false`** — critical. The default (`true`) would recursively chown the entire media library on every container start. With a large library this is slow and may conflict with Jellyfin's expected permissions.
- **`SCAN_ON_START=false`** — don't index the entire media library into FileRise's metadata on every start.
- **`TOTAL_UPLOAD_SIZE=10G`** — generous limit for large video files. Must match the NPM proxy config (see step 4).
- **Uploads volume on HDD** (`/hdd-almond-10tb/media`) — bulk data on the 10TB drive per storage layout convention.
- **Config volumes on NVMe** (`/sharedfolders/dev/config/filerise/`) — users/metadata are small files, belong on the fast drive.

Replace `YOUR_UID` and `YOUR_GID` with the owner of the media directories (check with `ls -ln`).

### 3. Create config directories

```bash
sudo mkdir -p /sharedfolders/dev/config/filerise/users
sudo mkdir -p /sharedfolders/dev/config/filerise/metadata
```

Set ownership to match PUID/PGID:

```bash
sudo chown -R YOUR_UID:YOUR_GID /sharedfolders/dev/config/filerise/
```

### 4. Update Jellyfin compose

Update Jellyfin's volume mounts to point at the new parent directory structure:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    network_mode: host
    volumes:
      - /sharedfolders/dev/config/jellyfin:/config
      - /sharedfolders/dev/cache/jellyfin:/cache
      - /hdd-almond-10tb/media/movies:/media/movies
      - /hdd-almond-10tb/media/tv:/media/tv
      - /hdd-almond-10tb/media/music:/media/music
      - /hdd-almond-10tb/media/photos:/media/photos
      - /hdd-almond-10tb/media/videos:/media/videos
    restart: unless-stopped
```

The only change is adding `media/` to each HDD path. Jellyfin's internal mount points (`/media/movies`, etc.) stay the same, so library configuration inside Jellyfin doesn't need updating.

### 5. NPM proxy host for FileRise

In Nginx Proxy Manager (http://192.168.0.113:81):

1. **Add Proxy Host**:
   - Domain: `files.tustin.house`
   - Scheme: `http`
   - Forward Host: `127.0.0.1`
   - Forward Port: `8090`
   - Enable: "Block Common Exploits", "Websockets Support"

2. **SSL tab**:
   - Select the `*.tustin.house` wildcard certificate
   - Force SSL: enabled

3. **Advanced tab** — paste this to allow large uploads:

   ```nginx
   client_max_body_size 10G;
   proxy_connect_timeout 36000s;
   proxy_read_timeout 36000s;
   proxy_send_timeout 36000s;
   send_timeout 36000s;
   proxy_request_buffering off;
   ```

   > `proxy_request_buffering off` is important — without it, NPM buffers the entire upload to disk before forwarding, which doubles disk writes and can fill temp space.

### 6. Cloudflare Tunnel

No changes needed. The existing wildcard route (`*.tustin.house → localhost:80`) already covers `files.tustin.house`. Cloudflare will route it to NPM, which proxies to FileRise on port 8090.

However, check Cloudflare's upload size limit for your plan:

| Cloudflare Plan | Max Upload Size |
|-----------------|-----------------|
| Free            | 100 MB          |
| Pro             | 100 MB          |
| Business        | 200 MB          |
| Enterprise      | 500 MB (default, configurable) |

If on the free plan, uploads >100 MB will be rejected by Cloudflare before reaching NPM. For large video files, users would need to connect via the local network (direct to NPM, bypassing the tunnel). This is a Cloudflare limitation, not a FileRise one — it applies equally to Seafile or any other upload tool.

### 7. Authentik OIDC setup

#### In Authentik (https://auth.tustin.house):

1. **Create an OAuth2/OpenID Provider**:
   - Name: `FileRise`
   - Authorization flow: default (implicit consent, or explicit if you prefer)
   - Client type: Confidential
   - Redirect URIs: `https://files.tustin.house/api/auth/auth.php?oidc=callback`
   - Signing key: select existing or create one
   - Scopes: `openid`, `email`, `profile`, `groups`
   - Note the **Client ID** and **Client Secret**

2. **Create an Application**:
   - Name: `FileRise`
   - Slug: `filerise`
   - Provider: select the provider above
   - Launch URL: `https://files.tustin.house`

3. **Create a Group** (if not already existing):
   - Name: `filerise-admins`
   - Add admin users to this group

#### In FileRise (https://files.tustin.house):

On first launch, FileRise prompts you to create a local admin account. Do this first, then:

1. Go to **Admin → OIDC & TOTP**
2. Configure:
   - Provider URL: `https://auth.tustin.house/application/o/filerise/`
   - Client ID: *(from Authentik)*
   - Client Secret: *(from Authentik)*
   - Redirect URI: `https://files.tustin.house/api/auth/auth.php?oidc=callback`
3. Click **Test OIDC discovery** to validate
4. Save

Users can now log in via the "Sign in with SSO" button. On first OIDC login, FileRise auto-creates a local account. Users in the `filerise-admins` Authentik group get admin privileges in FileRise.

### 8. Configure per-folder ACLs

After OIDC is working and users have logged in at least once (so their accounts exist in FileRise):

1. Go to **Admin → Folder Access**
2. For each media folder, set permissions per user:

| Folder | Admin | Uploader | Viewer |
|--------|-------|----------|--------|
| movies | Manage (Owner) | View (all), Upload, Rename | View (all) |
| tv | Manage (Owner) | View (all), Upload, Rename | View (all) |
| music | Manage (Owner) | View (all), Upload, Rename | View (all) |
| photos | Manage (Owner) | View (all), Upload | View (all) |
| videos | Manage (Owner) | View (all), Upload, Rename | View (all) |

Adjust per your needs. The key principle: uploaders can add content but only admins can delete.

### 9. Verify the integration

```bash
# Confirm FileRise is running
curl -fsS http://localhost:8090/ | head -5

# Confirm media directories are visible inside the container
docker exec filerise ls /var/www/uploads/
# Should show: movies  tv  music  photos  videos

# Confirm NPM proxy is working
curl -I https://files.tustin.house/
# Should return 200 (or 302 redirect to login)

# Upload a test file via the FileRise web UI, then confirm Jellyfin can see it
ls /hdd-almond-10tb/media/movies/
# Should show the uploaded file

# Trigger a Jellyfin library scan
curl -X POST 'http://localhost:8096/Library/Refresh' \
  -H 'Authorization: MediaBrowser Token=<jellyfin-api-key>'
```

## Startup Order

FileRise and Jellyfin are independent services in separate compose stacks. Neither depends on the other:

- **FileRise** writes files to the filesystem. It works regardless of whether Jellyfin is running.
- **Jellyfin** reads files from the filesystem. It works regardless of whether FileRise is running.

No cross-stack `depends_on` or startup sequencing is needed. This is a significant improvement over the seaf-fuse approach, which required careful startup ordering and a cron job.

## Maintainability

### What can go wrong

| Risk | Impact | Mitigation |
|------|--------|------------|
| FileRise container goes down | Users can't upload (Jellyfin unaffected — existing media still plays) | `restart: unless-stopped`, healthcheck |
| Disk full | Uploads fail, Jellyfin can't buffer | Monitor `/hdd-almond-10tb` usage (10TB drive) |
| Permission mismatch | FileRise can write but Jellyfin can't read, or vice versa | Set PUID/PGID to match directory ownership; `CHOWN_ON_START=false` |
| Cloudflare upload limit | Large files rejected on external access | Upload via local network for files >100MB (free plan) |
| FileRise CVE | Path traversal or ACL bypass | Keep image updated; Authentik SSO adds a second auth layer |

### Backups

- **Media files** (`/hdd-almond-10tb/media/`): up to you — these are user-uploaded media, typically replaceable.
- **FileRise config** (`/sharedfolders/dev/config/filerise/`): small files (users, ACLs, metadata). Include in NVMe backup routine. Critical file: `metadata/persistent_tokens.key` (encryption key for stored OIDC secrets).

### Seafile's role going forward

Seafile remains for its intended purpose: encrypted document storage, file sync, and collaboration. It is not involved in the Jellyfin media workflow at all. The `SEAFILE_ADD_FUSE.md` plan can be archived or deleted.

## Comparison: FileRise vs seaf-fuse

| Aspect | seaf-fuse | FileRise |
|--------|-----------|----------|
| Containers modified | Seafile (privileged) + Jellyfin | New standalone container |
| Privileged mode | Required | Not required |
| FUSE / kernel modules | Required | Not required |
| Cron jobs | Required (fuse auto-start) | Not required |
| Startup ordering | Critical (fuse must start before Jellyfin scans) | Independent (no ordering needed) |
| File path stability | UUID-prefixed, needs symlink layer | Direct filesystem paths |
| Write support | Read-only (via Seafile web UI) | Read-write (FileRise web UI) |
| Permission model | Seafile library sharing | Per-folder ACLs in FileRise |
| SSO | Via Seafile (already configured) | Native OIDC with Authentik |
| Performance overhead | Reconstructs files from chunks on every read | Zero — direct filesystem I/O |
| Failure mode | FUSE crash = Jellyfin sees empty dirs silently | FileRise crash = uploads stop, Jellyfin unaffected |

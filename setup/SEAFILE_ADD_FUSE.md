# Seafile FUSE Mount for Jellyfin Integration

## Problem Statement

Multiple users share a NAS running Jellyfin (media streaming) and Seafile (file storage). Users need to:

1. Upload videos/music that appear in Jellyfin for everyone
2. Keep personal files private — not visible to other users or Jellyfin
3. Do all of this through a simple web UI (non-technical users)

Jellyfin has no upload feature — it scans media from filesystem directories. Users need a way to get files into those directories without SSH, SCP, or any command-line tools.

## Rejected Alternatives

### Samba/SMB share
Adds a new service. Works well for local network but doesn't help remote users. Requires OS-level config (not Docker-managed), which conflicts with the OMV-managed setup.

### FileBrowser
Yet another service to maintain. Solves the upload problem but doesn't integrate with Seafile's existing user/permission model. Users would need to learn two different interfaces.

### Seafile API sync script
A cron job that copies files from Seafile to a plain directory via the Seafile API. Fragile — depends on API auth tokens, needs error handling for partial copies, and duplicates storage (files exist in both Seafile's internal format and as plain copies on disk).

### Direct filesystem sharing (pointing Jellyfin at Seafile's data directory)
Not possible. Seafile stores files in an internal chunked/encrypted format under its data directory (`/hdd-almond-10tb/seafile/`), not as plain files. Jellyfin cannot read this format.

### Rclone mount via WebDAV
Run an `rclone mount` container that connects to Seafile via WebDAV and exposes a local FUSE mount. Adds another service with its own failure modes, needs WebDAV auth tokens, and performance is worse than native seaf-fuse since reads go through HTTP instead of directly reading Seafile's block storage.

### seaf-cli (Seafile sync client)
Bidirectional sync to a plain directory. Duplicates all storage (synced copies exist alongside Seafile's internal blocks), requires per-library configuration, and adds another long-running process.

## Chosen Solution: Seafile FUSE Mount (`seaf-fuse`)

`seaf-fuse` is a built-in Seafile component that exposes libraries as a read-only POSIX filesystem via FUSE. It translates Seafile's internal storage format into a normal directory tree that any application (including Jellyfin) can read.

Ref: https://manual.seafile.com/13.0/extension/fuse/

### How it works

```
Seafile internal storage        seaf-fuse             Jellyfin
(chunked/encrypted blocks)  --> (FUSE mount)  -->  (reads plain files)
/hdd-almond-10tb/seafile/       /hdd-almond-10tb/     /media/movies
                                seafile-fuse/          /media/tv
                                <owner>/<id_lib>/      /media/music
```

The FUSE mount exposes a directory tree structured as:

```
/hdd-almond-10tb/seafile-fuse/
  admin@tustin.house/
    5403ac56-5552-4e31-a4f1-1de4eb889a5f_Movies/
      movie1.mp4
      movie2.mkv
    a1b2c3d4-e5f6-7890-abcd-ef1234567890_TV Shows/
      Breaking Bad/
        S01E01.mkv
    deadbeef-0000-1111-2222-333344445555_Music/
      artist/album/track.flac
  user@example.com/
    ffffffff-aaaa-bbbb-cccc-ddddeeee0000_My Private Library/
      personal-video.mp4
```

**Important:** Library folders are prefixed with their UUID (`{library_id}_{library_name}`), not just the library name. The UUIDs are assigned when libraries are created in Seafile and are visible in the Seafile web UI URL (e.g., `seafile.tustin.house/library/5403ac56-.../`). To make Jellyfin volume mounts manageable, we create symlinks on the host that map friendly names to the UUID-prefixed directories (see step 4).

Only the admin-owned shared libraries are bind-mounted into Jellyfin. Private user libraries exist in the FUSE tree but Jellyfin never sees them because they are not in its volume mounts.

### Limitations

- **Read-only** — seaf-fuse provides no write access. This is fine for Jellyfin (which only reads media) but means Jellyfin cannot create metadata sidecar files (`.nfo`, artwork) in the media directories. Jellyfin stores metadata in its `/config` volume instead, which is the default behavior.
- **Encrypted libraries are not accessible** — seaf-fuse cannot decrypt them. Only unencrypted libraries appear in the FUSE tree. Media libraries should be created without encryption.
- **No auto-start** — seaf-fuse must be started manually after each container restart (see Maintainability Risks).

### User workflow

| Role | Action | Result |
|------|--------|--------|
| **Admin** | Creates "Movies", "TV Shows", "Music" libraries in Seafile (unencrypted) | Libraries appear in FUSE mount |
| **Admin** | Shares each library with appropriate users (read/write) | Users see the library in their Seafile web UI |
| **User** | Uploads `movie.mp4` to the shared "Movies" library via Seafile web UI | File appears in FUSE mount; Jellyfin picks it up on next scan |
| **User** | Uploads personal files to their own private library | File is NOT visible to Jellyfin or other users |

### Privacy model

- **Shared libraries** (owned by admin, shared with users): visible in Jellyfin and in each user's Seafile UI
- **Private libraries** (owned by individual users): only visible to that user in Seafile, never exposed to Jellyfin
- Permissions are managed entirely through Seafile's web admin interface — no filesystem-level permission juggling

## Implementation

### 1. Create the FUSE mount point on the host

```bash
sudo mkdir -p /hdd-almond-10tb/seafile-fuse
```

### 2. Update the Seafile compose service

Add FUSE privileges and the bind mount with shared propagation so the FUSE filesystem is visible to the host (and therefore to other containers). Per the [official docs](https://manual.seafile.com/13.0/extension/fuse/):

```yaml
seafile:
  image: seafileltd/seafile-mc:13.0-latest
  container_name: seafile
  restart: unless-stopped
  ports:
    - "8080:80"
  privileged: true
  cap_add:
    - SYS_ADMIN
  devices:
    - /dev/fuse
  volumes:
    - /hdd-almond-10tb/seafile:/shared
    - type: bind
      source: /hdd-almond-10tb/seafile-fuse
      target: /seafile-fuse
      bind:
        propagation: rshared
  environment:
    # ... (all existing environment variables unchanged) ...
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_started
  networks:
    - seafile-net
```

Key additions vs. the base compose:
- `privileged: true` — required for FUSE inside Docker
- `cap_add: [SYS_ADMIN]` — grants the capability to mount filesystems
- `devices: [/dev/fuse]` — exposes the FUSE device to the container
- The bind mount with `propagation: rshared` — makes the FUSE mount visible to the host and other containers

### 3. Create the FUSE start script

Seafile's Docker image does not start `seaf-fuse` automatically. Create a helper script on the host at `/hdd-almond-10tb/seafile/scripts/start-fuse.sh`:

```bash
#!/bin/bash
# start-fuse.sh — starts seaf-fuse after Seafile server is ready
# Run with: docker exec seafile bash /scripts/start-fuse.sh

set -e

FUSE_MOUNT="/seafile-fuse"
SEAFILE_DIR="/opt/seafile/seafile-server-latest"

# Check if already mounted
if mountpoint -q "$FUSE_MOUNT"; then
  echo "seaf-fuse already mounted at $FUSE_MOUNT."
  exit 0
fi

echo "Starting seaf-fuse on $FUSE_MOUNT..."
cd "$SEAFILE_DIR"
./seaf-fuse.sh start "$FUSE_MOUNT"
echo "seaf-fuse started."
```

Mount the script into the container by adding to the Seafile service's volumes:

```yaml
volumes:
  - /hdd-almond-10tb/seafile:/shared
  - /hdd-almond-10tb/seafile/scripts/start-fuse.sh:/scripts/start-fuse.sh:ro
  - type: bind
    source: /hdd-almond-10tb/seafile-fuse
    target: /seafile-fuse
    bind:
      propagation: rshared
```

After the Seafile container starts and is healthy, start FUSE:

```bash
docker exec seafile bash /scripts/start-fuse.sh
```

To automate this on every restart, add a host-level cron job (see Maintainability section).

### 4. Create symlinks for Jellyfin volume mounts

Since FUSE paths include UUIDs (`{library_id}_{library_name}`), create symlinks on the host to provide stable, friendly paths for Jellyfin.

First, create the media libraries in Seafile (step 5 below), then find their UUIDs. The library ID is visible in the Seafile web UI URL when you open a library (e.g., `https://seafile.tustin.house/library/5403ac56-5552-4e31-a4f1-1de4eb889a5f/Movies/`). You can also list them from the FUSE mount:

```bash
ls /hdd-almond-10tb/seafile-fuse/admin@tustin.house/
# Output: 5403ac56-..._Movies  a1b2c3d4-..._TV Shows  deadbeef-..._Music  ...
```

Then create symlinks:

```bash
sudo mkdir -p /hdd-almond-10tb/seafile-media
sudo ln -s "/hdd-almond-10tb/seafile-fuse/admin@tustin.house/5403ac56-5552-4e31-a4f1-1de4eb889a5f_Movies" /hdd-almond-10tb/seafile-media/movies
sudo ln -s "/hdd-almond-10tb/seafile-fuse/admin@tustin.house/a1b2c3d4-e5f6-7890-abcd-ef1234567890_TV Shows" /hdd-almond-10tb/seafile-media/tv
sudo ln -s "/hdd-almond-10tb/seafile-fuse/admin@tustin.house/deadbeef-0000-1111-2222-333344445555_Music" /hdd-almond-10tb/seafile-media/music
sudo ln -s "/hdd-almond-10tb/seafile-fuse/admin@tustin.house/aaaabbbb-cccc-dddd-eeee-ffffffffffff_Photos" /hdd-almond-10tb/seafile-media/photos
sudo ln -s "/hdd-almond-10tb/seafile-fuse/admin@tustin.house/11112222-3333-4444-5555-666677778888_Videos" /hdd-almond-10tb/seafile-media/videos
```

(Replace the UUIDs above with the actual values after creating libraries.)

### 5. Update the Jellyfin compose service

Point Jellyfin at the symlink directory:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    network_mode: host
    volumes:
      - /sharedfolders/dev/config/jellyfin:/config
      - /sharedfolders/dev/cache/jellyfin:/cache
      - /hdd-almond-10tb/seafile-media/movies:/media/movies:ro
      - /hdd-almond-10tb/seafile-media/tv:/media/tv:ro
      - /hdd-almond-10tb/seafile-media/music:/media/music:ro
      - /hdd-almond-10tb/seafile-media/photos:/media/photos:ro
      - /hdd-almond-10tb/seafile-media/videos:/media/videos:ro
    restart: unless-stopped
```

> **Note:** Jellyfin must start AFTER `seaf-fuse` is running, otherwise the mount points will be empty. Since Jellyfin and Seafile are in separate compose stacks, this ordering is handled by starting the Seafile stack first and confirming the FUSE mount is active before starting Jellyfin.

### 6. Seafile admin setup (one-time, via web UI)

1. Log into Seafile as admin (`admin@tustin.house`)
2. Create libraries: "Movies", "TV Shows", "Music", "Photos", "Videos"
   - **Do NOT encrypt these libraries** — encrypted libraries are invisible to seaf-fuse
3. For each library, click Share and add users or groups with appropriate permissions (read-write for uploaders, read-only for viewers)
4. Note each library's UUID from the URL bar and create the symlinks (step 4 above)

### 7. Verify the integration

```bash
# Confirm FUSE mount is active inside the container
docker exec seafile mountpoint /seafile-fuse

# Confirm FUSE mount is visible on the host (bind propagation working)
ls /hdd-almond-10tb/seafile-fuse/
# Should show: admin@tustin.house/

# List exposed libraries (will show UUID-prefixed names)
ls /hdd-almond-10tb/seafile-fuse/admin@tustin.house/

# Confirm symlinks resolve
ls /hdd-almond-10tb/seafile-media/movies/

# Upload a test file via the Seafile web UI, then confirm it appears
ls /hdd-almond-10tb/seafile-media/movies/

# Trigger a Jellyfin library scan
curl -X POST 'http://localhost:8096/Library/Refresh' \
  -H 'Authorization: MediaBrowser Token=<jellyfin-api-key>'
```

## Automating seaf-fuse Startup

The Seafile Docker image does not start `seaf-fuse` on its own. The most practical approach for OMV is a host-level cron job that checks every minute:

```cron
* * * * * docker exec seafile mountpoint -q /seafile-fuse 2>/dev/null || docker exec seafile bash /scripts/start-fuse.sh >> /var/log/seaf-fuse-cron.log 2>&1
```

This is idempotent — if the mount is already active, it exits immediately. If Seafile isn't running yet (e.g., during boot), `docker exec` fails silently and retries next minute.

## Maintainability Risks

### FUSE mount failure breaks Jellyfin silently

If `seaf-fuse` crashes or the mount becomes stale, Jellyfin's media directories will appear empty. Jellyfin won't error — it will simply show no content. Users will see an empty library with no explanation.

**Mitigations:**
- The cron job above will detect and restart a failed mount within 1 minute
- Jellyfin library scan logs will show 0 items found — useful for debugging after the fact

### Library names and UUIDs are baked into paths

The symlinks reference both the admin email and library UUIDs. If the admin renames a library, the UUID stays the same but the directory name changes (it includes both). If the admin email changes, the top-level directory changes.

**Mitigation:** Treat library names as infrastructure. If a rename happens, update the symlink target. The symlink layer means Jellyfin's compose file never needs to change — only the symlinks.

### Bind propagation (`rshared`) requires native Linux Docker

The `rshared` propagation flag only works with native Linux Docker (which OMV uses). It does NOT work with Docker Desktop on macOS/Windows.

**Verification:** After setting up the mount, confirm from the host:
```bash
ls /hdd-almond-10tb/seafile-fuse/
# Should show the owner email directories, not be empty
```

### Performance overhead

`seaf-fuse` reconstructs files from Seafile's chunked storage on every read. For media streaming (sequential large-file reads), this is generally acceptable. However:
- Jellyfin library scans (which stat every file and read metadata) will be slower than direct filesystem access
- Very large libraries (thousands of files) may cause noticeably slow scans

### Container startup ordering across compose stacks

Seafile and Jellyfin are in separate compose stacks (per the project's architecture pattern). Docker Compose cannot enforce cross-stack `depends_on`. The cron job handles seaf-fuse startup, but Jellyfin may briefly see empty directories during boot until the FUSE mount comes up. Jellyfin handles this gracefully — it will just show an empty library until the next scheduled or manual scan.

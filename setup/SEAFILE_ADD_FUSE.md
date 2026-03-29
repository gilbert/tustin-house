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

## Chosen Solution: Seafile FUSE Mount (`seaf-fuse`)

`seaf-fuse` is a built-in Seafile component that exposes libraries as a read-only POSIX filesystem via FUSE. It translates Seafile's internal storage format into a normal directory tree that any application (including Jellyfin) can read.

### How it works

```
Seafile internal storage        seaf-fuse             Jellyfin
(chunked/encrypted blocks)  --> (FUSE mount)  -->  (reads plain files)
/hdd-almond-10tb/seafile/       /hdd-almond-10tb/     /media/movies
                                seafile-fuse/          /media/tv
                                <owner>/<library>/     /media/music
```

The FUSE mount exposes a directory tree structured as:

```
/hdd-almond-10tb/seafile-fuse/
  admin@tustin.house/
    Movies/
      movie1.mp4
      movie2.mkv
    TV Shows/
      Breaking Bad/
        S01E01.mkv
    Music/
      artist/album/track.flac
  user@example.com/
    My Private Library/     <-- exists in FUSE but NOT mounted into Jellyfin
      personal-video.mp4
```

Only the admin-owned shared libraries are bind-mounted into Jellyfin. Private user libraries exist in the FUSE tree but Jellyfin never sees them because they are not in its volume mounts.

### User workflow

| Role | Action | Result |
|------|--------|--------|
| **Admin** | Creates "Movies", "TV Shows", "Music" libraries in Seafile | Libraries appear in FUSE mount |
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

Add FUSE device access, the `SYS_ADMIN` capability, and the new bind mount with shared propagation so the FUSE filesystem is visible to the host (and therefore to other containers):

```yaml
seafile:
  image: seafileltd/seafile-mc:13.0-latest
  container_name: seafile
  restart: unless-stopped
  ports:
    - "8080:80"
  cap_add:
    - SYS_ADMIN
  devices:
    - /dev/fuse
  volumes:
    - /hdd-almond-10tb/seafile:/shared
    - /hdd-almond-10tb/seafile-fuse:/seafile-fuse:rshared
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

### 3. Create a custom entrypoint wrapper

Seafile's Docker image has its own entrypoint. We need to start `seaf-fuse` after the main Seafile server is up. Create this script on the host at `/hdd-almond-10tb/seafile/scripts/start-fuse.sh`:

```bash
#!/bin/bash
# start-fuse.sh — starts seaf-fuse after Seafile server is ready
# Mounted into the Seafile container; called by a supervisor process or cron

set -e

FUSE_MOUNT="/seafile-fuse"
SEAFILE_DIR="/opt/seafile/seafile-server-latest"

# Wait for seafile-server to be running
echo "Waiting for Seafile server to start..."
until pgrep -f "seafile-controller" > /dev/null 2>&1; do
  sleep 5
done
echo "Seafile server is running."

# Start seaf-fuse if not already running
if ! mountpoint -q "$FUSE_MOUNT"; then
  echo "Starting seaf-fuse on $FUSE_MOUNT..."
  "$SEAFILE_DIR/bin/seaf-fuse" start "$FUSE_MOUNT"
  echo "seaf-fuse started."
else
  echo "seaf-fuse already mounted."
fi
```

Mount the script into the container by adding to the Seafile service's volumes:

```yaml
volumes:
  - /hdd-almond-10tb/seafile:/shared
  - /hdd-almond-10tb/seafile-fuse:/seafile-fuse:rshared
  - /hdd-almond-10tb/seafile/scripts/start-fuse.sh:/scripts/start-fuse.sh:ro
```

After the Seafile container starts, exec into it to start FUSE:

```bash
docker exec seafile bash /scripts/start-fuse.sh
```

To automate this on every restart, add a healthcheck-triggered approach or use a host-level systemd timer (see Maintainability Risks below for options).

### 4. Update the Jellyfin compose service

Replace the direct HDD paths with read-only mounts from the FUSE tree. The `admin@tustin.house` path segment must match the Seafile admin's email, and the library names must match exactly (case-sensitive):

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    network_mode: host
    volumes:
      - /sharedfolders/dev/config/jellyfin:/config
      - /sharedfolders/dev/cache/jellyfin:/cache
      - /hdd-almond-10tb/seafile-fuse/admin@tustin.house/Movies:/media/movies:ro
      - /hdd-almond-10tb/seafile-fuse/admin@tustin.house/TV Shows:/media/tv:ro
      - /hdd-almond-10tb/seafile-fuse/admin@tustin.house/Music:/media/music:ro
      - /hdd-almond-10tb/seafile-fuse/admin@tustin.house/Photos:/media/photos:ro
      - /hdd-almond-10tb/seafile-fuse/admin@tustin.house/Videos:/media/videos:ro
    restart: unless-stopped
```

> **Note:** Jellyfin must start AFTER `seaf-fuse` is running, otherwise the mount points will be empty. Since Jellyfin and Seafile are in separate compose stacks, this ordering is handled by starting the Seafile stack first and confirming the FUSE mount is active before starting Jellyfin.

### 5. Seafile admin setup (one-time, via web UI)

1. Log into Seafile as admin (`admin@tustin.house`)
2. Create libraries: "Movies", "TV Shows", "Music", "Photos", "Videos"
3. For each library, click Share and add users or groups with appropriate permissions (read-write for uploaders, read-only for viewers)

### 6. Verify the integration

```bash
# Confirm FUSE mount is active
docker exec seafile mountpoint /seafile-fuse

# List exposed libraries
ls /hdd-almond-10tb/seafile-fuse/admin@tustin.house/

# Upload a test file via the Seafile web UI, then confirm it appears
ls /hdd-almond-10tb/seafile-fuse/admin@tustin.house/Movies/

# Trigger a Jellyfin library scan
curl -X POST 'http://localhost:8096/Library/Refresh' \
  -H 'Authorization: MediaBrowser Token=<jellyfin-api-key>'
```

## Maintainability Risks

### seaf-fuse must be started manually after container restart

The Seafile Docker image's entrypoint does not start `seaf-fuse` automatically. After every container restart (host reboot, Docker update, OMV compose restart), someone must run `docker exec seafile bash /scripts/start-fuse.sh` or the FUSE mount will be down and Jellyfin will see empty libraries.

**Mitigations:**
- A host-level systemd service/timer that runs the exec command after the Seafile container is healthy
- A cron job on the host: `* * * * * docker exec seafile mountpoint -q /seafile-fuse || docker exec seafile bash /scripts/start-fuse.sh`
- Wrapping the Seafile image with a custom Dockerfile that adds `seaf-fuse start` to the entrypoint (most robust but adds a custom image to maintain)

### FUSE mount failure breaks Jellyfin silently

If `seaf-fuse` crashes or the mount becomes stale, Jellyfin's media directories will appear empty. Jellyfin won't error — it will simply show no content. Users will see an empty library with no explanation.

**Mitigations:**
- Monitor the mount with a periodic health check: `mountpoint -q /hdd-almond-10tb/seafile-fuse`
- Jellyfin library scan logs will show 0 items found — useful for debugging after the fact

### Library names are path-sensitive

The Jellyfin volume mounts hard-code Seafile library names ("Movies", "TV Shows", etc.). If the admin renames a library in the Seafile UI, the FUSE path changes and Jellyfin loses access. The compose file must be updated to match.

**Mitigation:** Document the library names clearly and treat them as infrastructure — renaming requires a compose update and Jellyfin restart.

### Admin email is baked into mount paths

The FUSE tree is organized by owner email (`admin@tustin.house`). If the admin account's email changes, all Jellyfin volume paths break.

**Mitigation:** This is unlikely to change, but worth noting. A symlink on the host could add a layer of indirection if needed.

### Bind propagation (`rshared`) requires Docker to be running with mount propagation support

Most modern Docker/Linux setups support this, but OMV's Docker configuration should be verified. If propagation doesn't work, the FUSE mount inside the container won't be visible to the host or to Jellyfin.

**Verification:** After setting up the mount, confirm from the host:
```bash
ls /hdd-almond-10tb/seafile-fuse/
# Should show the owner email directories, not be empty
```

### Performance overhead

`seaf-fuse` reconstructs files from Seafile's chunked storage on every read. For media streaming (sequential large-file reads), this is generally acceptable. However:
- Jellyfin library scans (which stat every file and read metadata) will be slower than direct filesystem access
- Very large libraries (thousands of files) may cause noticeably slow scans
- No write access — this is inherently read-only, which is correct for Jellyfin but means Jellyfin cannot create metadata sidecar files (`.nfo`, artwork) in the media directories. Jellyfin stores metadata in its `/config` volume instead, which is the default behavior.

### Container startup ordering across compose stacks

Seafile and Jellyfin are in separate compose stacks (per the project's architecture pattern). Docker Compose cannot enforce cross-stack `depends_on`. The operator must ensure Seafile is up and `seaf-fuse` is mounted before starting Jellyfin.

**Mitigation:** A wrapper script or systemd unit that starts Seafile, waits for the FUSE mount, then starts Jellyfin.

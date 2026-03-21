# tustin.house NAS — Full Context, Setup & Current Status

## Project Goal
Build a home NAS for a friend. Requirements:
- Media hosting (movies, TV, music, photos, general storage)
- Encrypted document storage for sensitive files
- External access for multiple non-techie users
- Single sign-on across all services
- Cold storage, all in one box, single power cable
- OpenMediaVault (OMV) 7 as NAS OS
- Jellyfin for media streaming
- Seafile for encrypted documents
- Authentik for SSO
- Cloudflare Tunnel for external access (no port forwarding)
- Tailscale for admin SSH access

---

## Hardware (All Purchased & Assembled)

| Component | Part | Notes |
|---|---|---|
| Motherboard | Gigabyte B550M DS3H AC R2 (Micro-ATX, AM4) | 4x SATA natively |
| CPU | AMD Ryzen 7 5800XT (8c/16t, up to 4.7GHz) | **NO integrated graphics** — needs discrete GPU for display output |
| RAM | G.Skill Ripjaws V 16GB (2x8GB) DDR4-3200 | Included in Micro Center bundle |
| Boot Drive | 256GB M.2 NVMe SSD | OS only, installed in M.2 slot |
| Storage Drive | WD Red Pro 10TB 3.5" HDD (WD103KFBX) | 12V peak 1.9A |
| Case | Fractal Design Node 804 (FD-CA-NODE-804-BL-W) | 8x 3.5" bays, no hot-swap |
| PSU | be quiet! Pure Power 13 M 650W (fully modular, 80+ Gold) | Standard ATX |

**Bundle:** Motherboard + CPU + RAM purchased at Micro Center for $299.

**Critical hardware note:** The 5800XT has NO iGPU. Motherboard HDMI/DP outputs are non-functional with this CPU. A borrowed discrete GPU in the PCIe x16 slot is used for initial setup only. NAS runs headless in normal operation.

---

## Build History / Why We're Here

1. **Raspberry Pi 5 + Radxa Penta SATA HAT** — HAT burned out. WD Red Pro draws 1.9A peak on 12V; Radxa HAT max is 1.7A.
2. **Pi 5 + PCIe FFC adapter + SATA controller in Node 804** — Abandoned. Waveshare FFC board doesn't supply 3.3V/5V; ASM1064 SATA card needs 3.3V.
3. **JONSBO N2 + CWWK N305 board** — Abandoned. Grey-market Chinese OEM, inconsistent availability.
4. **Micro Center Mini-ITX gaming boards** — All max 2 SATA ports. Wrong tool.
5. **Current build: Micro-ATX in Node 804** — Clean solution. Name brand parts, same-day Micro Center pickup, 4 SATA ports, expandable via PCIe SATA card.

---

## Network & Access Details

| Item | Value |
|---|---|
| NAS local IP | 192.168.0.113 |
| Domain | tustin.house (registered via Cloudflare registrar) |
| Tailscale | Installed and enabled, auto-starts on boot |
| Cloudflare Tunnel | Running via Docker (`cloudflared` compose stack) |
| SSH access | Key-based via local network; OMV stores keys in `/var/lib/openmediavault/ssh/authorized_keys/%u` |

---

## Storage Layout

- **Boot:** NVMe SSD → OMV OS only
- **Data:** WD Red Pro 10TB → mounted at `/srv/dev-disk-by-uuid-e9c634f8-8446-427e-b520-fd71dd239cac/`
- **Filesystem:** ext4, mounted via OMV

### Shared Folders (all on WD Red Pro via OMV)

| Name | Path |
|---|---|
| movies | dev/movies/ |
| tv | dev/tv/ |
| music | dev/music/ |
| photos | dev/photos/ |
| videos | dev/videos/ |
| documents | dev/documents/ |
| compose | dev/compose/ |
| compose-data | dev/compose-data/ |

OMV shared folders are accessible at `/sharedfolders/[name]` within Docker containers.

---

## Target Service Stack

| Service | Purpose | URL | Port |
|---|---|---|---|
| Jellyfin | Media streaming | jellyfin.tustin.house | 8096 |
| Seafile | Encrypted document storage | seafile.tustin.house | 8080 |
| Authentik | Single sign-on | auth.tustin.house | 9000 |
| Nginx Proxy Manager | Reverse proxy | npm.tustin.house | 81 (admin), 80 (proxy) |
| Cloudflare Tunnel | External access | — | — |
| Tailscale | Admin SSH access | — | — |

### Traffic Flow
```
Internet → Cloudflare Tunnel → Nginx Proxy Manager (port 80) → individual services
Tailscale → direct SSH to NAS (admin only)
```

---

## Cloudflare Tunnel Public Hostnames

| Subdomain | Domain | Type | URL |
|---|---|---|---|
| * | tustin.house | HTTP | localhost:80 |

> Wildcard `*` subdomain points at NPM on port 80. NPM handles internal routing to each service.
> Add new proxy hosts in NPM when deploying new services — no new Cloudflare tunnel entries needed.

**DNS note:** The wildcard `*.tustin.house` DNS record covers all subdomains via the tunnel. Safari (and some browsers) may cache old DNS — clear DNS cache if a subdomain works in one browser but not another.

---

## Nginx Proxy Manager

- **Admin UI:** http://192.168.0.113:81
- **Wildcard SSL cert:** `*.tustin.house` + `tustin.house` via Cloudflare DNS challenge
- **API token:** Cloudflare DNS challenge token saved in NPM

### Proxy Hosts Configured

| Domain | Forward Port | SSL | Notes |
|---|---|---|---|
| jellyfin.tustin.house | 8096 | Wildcard cert | |
| auth.tustin.house | 9000 | Wildcard cert | |
| seafile.tustin.house | 8080 | Wildcard cert | Advanced tab config required (see seafile section) |

> Use wildcard cert for all new proxy hosts — no need to request new certs.

---

## Docker Compose Stacks

All compose files live in `/sharedfolders/compose/` (managed via OMV → Services → Compose → Files).

### jellyfin (✅ Running)

**Compose file:** [`setup/jellyfin-docker-compose.yml`](setup/jellyfin-docker-compose.yml)

### nginx-proxy-manager (✅ Running)

**Compose file:** [`setup/npm-docker-compose.yml`](setup/npm-docker-compose.yml)

### cloudflared (✅ Running)

**Compose file:** [`setup/cloudflared-docker-compose.yml`](setup/cloudflared-docker-compose.yml)

### authentik (✅ Running)

All four containers share a bridge network so postgres and redis are never exposed on the host. Only port 9000 is published for NPM to reach. **Do not** use `network_mode: host` for postgres or redis — it would expose standard ports on the host and conflict with other services (e.g. Seafile) that also run postgres.

**Compose file:** [`setup/authentik-docker-compose.yml`](setup/authentik-docker-compose.yml) — includes volume permission and first-time setup notes in comments.

### seafile (✅ Running)

Seafile CE 13.0 with MariaDB 10.11, Redis, and notification server. Uses a dedicated bridge network — only port 8080 (Seafile's internal nginx) and 8083 (notification server WebSocket) are published to the host. MariaDB and Redis are internal only.

**Key architecture notes (Seafile 13):**
- The `seafileltd/seafile-mc:13.0-latest` image runs its own internal nginx — only port 80 needs to be published (mapped to 8080 on host). All paths (`/seafhttp`, `/seafdav`, `/notification`) are proxied internally.
- The notification server is a separate container (`seafileltd/notification-server:13.0-latest`) configured via environment variables (not config file mounts).
- Both the main seafile container and notification-server must share the same `JWT_PRIVATE_KEY`.
- MariaDB uses a healthcheck with `condition: service_healthy` to prevent "mysql is not ready" bootstrap failures.
- `ENABLE_GO_FILESERVER=true` enables the Go-based file server (faster than the legacy Python one).

**Compose file:** [`setup/seafile-docker-compose.yml`](setup/seafile-docker-compose.yml)

> Generate JWT key with: `openssl rand -hex 32`
> Same JWT key must be used in both `seafile` and `notification-server` containers.
> `INIT_*` env vars are only used on first bootstrap — they are ignored on subsequent starts.

**NPM Advanced Config:** [`setup/seafile-npm-advanced.conf`](setup/seafile-npm-advanced.conf) — paste into the Advanced tab of the `seafile.tustin.house` proxy host.

> NPM proxy host settings: Scheme `http`, Forward Host `127.0.0.1`, Forward Port `8080`. Enable "Block Common Exploits" and "Websockets Support". SSL tab: select `*.tustin.house` wildcard cert, force SSL.

---

## Jellyfin SSO (✅ Configured)

Jellyfin is wired into Authentik via the Jellyfin SSO plugin using OAuth2/OIDC.

### Authentik side
- **Provider:** OAuth2/OpenID, type `Confidential`, named `Jellyfin`
- **Redirect URI:** `https://jellyfin.tustin.house/sso/OID/redirect/authentik`
- **Application:** slug `jellyfin`, linked to above provider

### Jellyfin side
- **Plugin:** SSO Authentication (installed via Dashboard → Plugins → Catalog)
- **Provider name:** `authentik`
- **OIDC endpoint:** `https://auth.tustin.house/application/o/jellyfin/`
- **Base URL:** `https://jellyfin.tustin.house` ← critical: must be `https://` or redirect URI mismatch occurs
- **Enable authorization:** ✅
- **Enable folder creation:** ✅ (auto-creates Jellyfin user on first SSO login)

**SSO login URL:** `https://jellyfin.tustin.house/sso/OID/start/authentik`

**Login page customization (✅ Done):** The login page is customized via the Jellyfin Branding API (`/System/Configuration/branding`) using two fields:

- **`CustomCss`** — injected as a raw `<style>` tag (bypasses DOMPurify). Hides the default visual login (user tiles), manual login form, and utility buttons (Manual Login, Forgot Password, Change Server). Reorders the disclaimer to the top via flexbox `order: -1`. Styles the SSO button. Uses `#loginPage:has(.admin-toggle-cb:checked) .manualLoginForm` to reveal Jellyfin's built-in login form when the toggle checkbox is checked.
- **`LoginDisclaimer`** — sanitized by DOMPurify (no `<style>`, `<script>`, or event handlers). Contains the SSO form button and a pure CSS checkbox hack (`<input type="checkbox">` + `<label>`) for the "Sign in with username instead" toggle.

**Key constraint:** DOMPurify (default config) strips `<style>`, `<script>`, and all event handlers (`onclick`, etc.) from LoginDisclaimer. Use `CustomCss` for all styling and interaction logic (CSS-only). The `:has()` selector enables cross-DOM toggling from the checkbox in the disclaimer to the `.manualLoginForm` elsewhere in the page.

**API key:** A Jellyfin API key (`claude`) is stored in `/home/ai/tustin-house/.env` (gitignored). Used with `Authorization: MediaBrowser Token=<key>` header. The correct endpoint for writing branding config is `POST /System/Configuration/branding` (not `/Branding/Configuration`, which is read-only GET).

### Adding new Authentik users to Jellyfin
1. In Authentik admin (`https://auth.tustin.house/if/admin/`), go to Directory → Users → Create
2. Set username, name, email, then set a password for the user
3. No extra policy bindings needed — all Authentik users can access the Jellyfin app by default
4. User visits the SSO login URL (or clicks the button on the login page) and a Jellyfin account is auto-created on first login (via "Enable folder creation" in the SSO plugin)

---

## Seafile SSO (✅ Configured)

Seafile is wired into Authentik via OAuth2/OIDC, configured in `seahub_settings.py`.

### Authentik side
- **Provider:** OAuth2/OpenID Connect, named `Seafile`
- **Redirect URI:** `https://seafile.tustin.house/oauth/callback/`
- **Application:** slug `seafile`, linked to above provider

### Seafile side
- **Config file:** `/shared/seafile/conf/seahub_settings.py` inside the `seafile` container (host path: `/sharedfolders/dev/compose-data/seafile/data/seafile/conf/seahub_settings.py`)
- **OAuth reference config:** [`setup/seafile-seahub-oauth.py`](setup/seafile-seahub-oauth.py)
- **Auto-create users:** ✅ (`OAUTH_CREATE_UNKNOWN_USER = True`)
- **Auto-activate users:** ✅ (`OAUTH_ACTIVATE_USER_AFTER_CREATION = True`)
- **Attribute mapping:** Authentik `sub` → Seafile `uid` (required), `email` → `contact_email` (required), `name` → `name` (optional)

The login page shows a **"Single Sign-On"** button. Users click it, authenticate via Authentik, and a Seafile account is auto-created on first login.

### Adding new users to Seafile
1. Create the user in Authentik (Directory → Users → Create) with username, email, and password
2. User visits https://seafile.tustin.house and clicks "Single Sign-On"
3. Seafile account is auto-created on first SSO login

---

## Claude Code on the NAS (`ai` user)

Claude Code is installed on the NAS under a dedicated non-root `ai` user for security isolation. If prompt injection occurs, the blast radius is limited to Docker containers and compose files — no root access to the OS.

### User setup (already done)
```bash
useradd -m -s /bin/bash ai
usermod -aG docker ai      # docker access without root
usermod -aG _ssh ai         # SSH access (OMV restricts SSH to root and _ssh groups)
chown -R ai:ai /sharedfolders/compose/   # write access to compose files
```

### SSH key setup
OMV does not use `~/.ssh/authorized_keys`. Keys are stored at:
```
/var/lib/openmediavault/ssh/authorized_keys/<username>
```
The `ai` user's key file was copied from root's and ownership set:
```bash
cp /var/lib/openmediavault/ssh/authorized_keys/root /var/lib/openmediavault/ssh/authorized_keys/ai
chown ai:ai /var/lib/openmediavault/ssh/authorized_keys/ai
```

### SSH config (`/etc/ssh/sshd_config`)
```
AuthorizedKeysFile .ssh/authorized_keys .ssh/authorized_keys2 /var/lib/openmediavault/ssh/authorized_keys/%u
PubkeyAuthentication yes
AllowGroups root _ssh
```

### Connecting
```bash
ssh ai@tustinhouse.local
claude
```

### What `ai` can do
- Read/write compose files in `/sharedfolders/compose/`
- Run `docker` and `docker compose` commands
- Cannot modify OMV config, OS files, or anything outside its permissions
- For operations requiring root (e.g. `chown` volume dirs for new services), ask the human operator

---

## Current Status

| Task | Status |
|---|---|
| Hardware assembled | ✅ Done |
| OMV 7 installed | ✅ Done |
| WD Red Pro formatted (ext4) + mounted | ✅ Done |
| Shared folders created | ✅ Done |
| omv-extras / compose plugin installed | ✅ Done |
| Tailscale installed + auto-start enabled | ✅ Done |
| Jellyfin deployed + accessible externally | ✅ Done |
| Nginx Proxy Manager deployed | ✅ Done |
| Cloudflare Tunnel deployed (wildcard `*.tustin.house`) | ✅ Done |
| Wildcard SSL cert (*.tustin.house) | ✅ Done |
| Authentik deployed | ✅ Done |
| Jellyfin wired into Authentik SSO | ✅ Done |
| `ai` user created for Claude Code on NAS | ✅ Done |
| Claude Code installed on NAS | ✅ Done |
| Jellyfin SSO login button on login page | ✅ Done |
| Seafile deployed | ✅ Done |
| Seafile NPM proxy host configured | ✅ Done |
| Seafile wired into Authentik SSO | ✅ Done |

---

## Immediate Next Steps

1. ~~Install Claude Code on the NAS~~ ✅
2. ~~Add SSO login button to Jellyfin login page~~ ✅
3. ~~Deploy Seafile~~ ✅
4. ~~Add `seafile.tustin.house` proxy host in NPM~~ ✅
5. ~~Wire Seafile into Authentik SSO~~ ✅
6. ~~Create user accounts in Seafile~~ ✅ (handled by SSO — accounts auto-created on first login)
7. Instruct users on creating encrypted libraries for sensitive documents

---

## Key Technical Notes

- WD Red Pro 10TB draws 12V @ 1.9A peak — exceeds Radxa HAT's 1.7A limit (learned the hard way)
- 5800XT has NO iGPU — motherboard video outputs are dead with this CPU. Fine for headless NAS.
- B550M DS3H AC R2 has 4x SATA (not 6). Add PCIe SATA expansion card (~$25) to go beyond 4 drives.
- Node 804 drive bays: no hot-swap, screw-mount trays. Fine for cold storage NAS use.
- Boot NVMe is OS only — all data lives on WD Red Pro.
- OMV is Debian-based — all standard Debian/Linux commands work over SSH.
- Default OMV web login: `admin / openmediavault` — already changed.
- Default SSH login: `root` + password set during install.
- fTPM prompt on boot: press N (twice if needed). Can be permanently disabled in BIOS under Advanced → AMD fTPM configuration → Disabled.
- Jellyfin and NPM use `network_mode: host`. Services with internal dependencies (Authentik, Seafile) use dedicated bridge networks with only the necessary ports published to the host.
- Cloudflare tunnel handles TLS termination externally; internal traffic is HTTP.
- NPM wildcard cert covers all current and future `*.tustin.house` subdomains — select it when adding new proxy hosts, no need to request new certs.
- When deploying new services that need a database: always use a dedicated bridge network per stack, never `network_mode: host` for the database. This avoids port conflicts between stacks.
- Docker volume permissions: authentik-server/worker run as UID 1000, postgres as UID 999. `chown` the host paths before first start or gunicorn/postgres will fail with permission errors.
- Seafile 13 has its own internal nginx — only publish port 80 (mapped to 8080 on host). Don't publish individual service ports (8082, 8000, etc.) — the internal nginx handles routing.

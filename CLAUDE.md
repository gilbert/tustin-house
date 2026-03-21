# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home NAS server ("tustin.house") for a friend. Hardware is a Micro-ATX build (Ryzen 7 5800XT, B550M DS3H AC R2, Node 804 case) running OpenMediaVault 7 headless. The repo tracks documentation, configuration, and 3D-printable case files — there is no application source code to build or test.

## Service Stack

All services run as Docker Compose stacks managed via OMV (files live on the NAS at `/sharedfolders/compose/`). The compose files in this repo are documentation — the live copies are on the NAS.

- **Jellyfin** — media streaming (port 8096, `network_mode: host`)
- **Nginx Proxy Manager** — reverse proxy (port 81 admin, port 80 proxy, `network_mode: host`)
- **Cloudflare Tunnel** — external access, wildcard `*.tustin.house` → NPM port 80
- **Authentik** — SSO (port 9000, dedicated bridge network with its own postgres/redis)
- **Seafile** — encrypted document storage (port 8080, dedicated bridge network)
- **Immich** — photo/video backup (port 2283, dedicated bridge network with postgres/redis/ML)

## Architecture Patterns

- Services without internal dependencies (Jellyfin, NPM, cloudflared) use `network_mode: host`
- Services with databases (Authentik, future Seafile) use dedicated bridge networks per stack — only the app port is published. Never use `network_mode: host` for postgres/redis to avoid port conflicts between stacks.
- All subdomains route: Internet → Cloudflare Tunnel → NPM (port 80) → service. New services only need a proxy host in NPM using the existing wildcard SSL cert.

## Jellyfin SSO Login Page

The Jellyfin login page is customized via the Branding API (`POST /System/Configuration/branding`). Two fields matter:

- **`CustomCss`** — injected as a raw `<style>` tag (bypasses DOMPurify). All styling and CSS-only interaction logic goes here.
- **`LoginDisclaimer`** — sanitized by DOMPurify (no `<style>`, `<script>`, or event handlers). Contains the SSO button and a pure CSS checkbox toggle for revealing manual login.

The `:has()` selector enables cross-DOM toggling: a checkbox in the disclaimer controls visibility of `.manualLoginForm` elsewhere on the page. The Jellyfin API key is in `.env` (gitignored), used with `Authorization: MediaBrowser Token=<key>` header.

## Claude Code on the NAS

Claude Code runs on two machines. These instructions apply only when running **on the NAS** (as the `ai` user via SSH):

- Can read/write compose files and run `docker`/`docker compose` commands but cannot modify OMV config or OS files. Operations requiring root (e.g., `chown` for new service volume dirs) must be done by the human operator.
- Outbound network access is restricted by a squid proxy whitelist. If a task requires fetching from a domain that isn't whitelisted, use `/request-domain` to ask the human operator to add it. Check `setup/squid.conf` for the current allowed domains before requesting. Never attempt to bypass the proxy.

When running locally (e.g., on a laptop against this repo), these restrictions do not apply.

## Key Constraints

- The 5800XT has no iGPU — motherboard video outputs are non-functional. NAS is headless.
- WD Red Pro 10TB draws 12V @ 1.9A peak — this is why the original Radxa SATA HAT burned out.
- Docker volume permissions: Authentik server/worker run as UID 1000, postgres as UID 999. Must `chown` host paths before first start.
- NPM wildcard cert covers all `*.tustin.house` subdomains — select it when adding proxy hosts, don't request new certs.
- OMV SSH keys are stored at `/var/lib/openmediavault/ssh/authorized_keys/<username>`, not `~/.ssh/authorized_keys`.

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

## AI User Network Restrictions

The `ai` Linux user runs Claude Code with `--dangerously-skip-permissions`. To limit its network access, outbound HTTP/HTTPS is restricted to whitelisted domains via a squid proxy + nftables.

### How it works

- **Squid proxy** (`setup/squid.conf`) — only allows requests to domains listed in the `claude_domains` ACL
- **nftables rules** (`setup/ai-restrict.conf`) — blocks direct port 80/443 from the `ai` user, forcing all traffic through the proxy
- **systemd service** (`setup/ai-restrict.service`) — persists the nftables rules across reboots

### Deploy

```bash
# Squid config
scp setup/squid.conf root@tustinhouse.local:/etc/squid/squid.conf
ssh root@tustinhouse.local 'systemctl restart squid'

# nftables rules
ssh root@tustinhouse.local 'mkdir -p /etc/nftables.d'
scp setup/ai-restrict.conf root@tustinhouse.local:/etc/nftables.d/ai-restrict.conf
ssh root@tustinhouse.local 'nft -f /etc/nftables.d/ai-restrict.conf'

# Systemd service (first time only)
scp setup/ai-restrict.service root@tustinhouse.local:/etc/systemd/system/ai-restrict.service
ssh root@tustinhouse.local 'systemctl daemon-reload && systemctl enable ai-restrict'
```

### Adding a domain to the whitelist

Edit `setup/squid.conf` and add the domain to the `acl claude_domains` line:

```
acl claude_domains dstdomain .anthropic.com .github.com .example.com
```

Then redeploy the squid config:

```bash
scp setup/squid.conf root@tustinhouse.local:/etc/squid/squid.conf
ssh root@tustinhouse.local 'systemctl restart squid'
```

### Proxy environment

The `ai` user needs these in its shell profile (`~ai/.bashrc`):

```bash
export HTTP_PROXY=http://127.0.0.1:3128
export HTTPS_PROXY=http://127.0.0.1:3128
```

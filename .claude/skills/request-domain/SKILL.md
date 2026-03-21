---
name: request-domain
description: Request access to a new domain through the squid proxy whitelist. Use when a tool or task requires network access to a domain that is currently blocked.
disable-model-invocation: false
argument-hint: [domain]
---

# Requesting Domain Access

You are running behind a squid proxy that restricts outbound network access to a whitelist of domains. If you need to access a domain that is not currently whitelisted, you **cannot** add it yourself.

## How to request access

1. Tell the user which domain you need access to and why.
2. Provide the exact line they need to add to the squid ACL. The format is:

```
acl claude_domains dstdomain .example.com
```

The domain should be prefixed with `.` to allow all subdomains.

3. Tell the user to run these commands on the host (as root):

```bash
# Edit the squid config
sudo nano /etc/squid/squid.conf

# Add the domain to the existing claude_domains ACL line, e.g.:
# acl claude_domains dstdomain .anthropic.com .github.com .example.com

# Then restart squid
sudo systemctl restart squid
```

Alternatively, they can edit the local `setup/squid.conf` in this repo, scp it to the server, and restart:

```bash
scp setup/squid.conf root@tustinhouse.local:/etc/squid/squid.conf
ssh root@tustinhouse.local 'systemctl restart squid'
```

4. After the user confirms the domain has been added, retry the operation.

## Current whitelist

The current allowed domains are defined in `setup/squid.conf` on the `acl claude_domains` line. Read that file to check if a domain is already whitelisted before requesting access.

## Important

- Never attempt to bypass the proxy or modify proxy settings yourself.
- Always check `squid.conf` first — the domain may already be allowed.
- Group your requests if you need multiple domains at once.

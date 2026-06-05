# Tailscale 私網設定指南

> Set up a private encrypted mesh between M1, workstation, and phone.
> All services stay bound to 127.0.0.1; Tailscale ACLs decide who can reach what.

---

## 1. Install Tailscale

### macOS (M1)

```bash
# Option A: App Store
# Search "Tailscale" and install

# Option B: Homebrew
brew install --cask tailscale

# Option C: Direct download
# https://tailscale.com/download/mac
```

### Linux (workstation)

```bash
# Fedora
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled

# Ubuntu (same)
```

### iOS / Android (optional)

Install from App Store / Play Store. Sign in to your tailnet.

## 2. Sign in

```bash
# On each machine
sudo tailscale up
# A URL is printed; open it in a browser; sign in with Google/Microsoft/GitHub
```

After sign-in, each machine has a Tailscale IP (100.x.x.x).

## 3. Verify the mesh

```bash
# On M1
tailscale status
# Should show: m1 (this machine), station (peer), phone (peer, if added)

tailscale ping station

# On workstation
tailscale ping m1
```

✅ **Done when**: both `ping` commands succeed.

## 4. Magic DNS

Tailscale assigns each machine a hostname like `m1.tail-xxxx.ts.net`.

```bash
# From workstation
ping m1.tail-xxxx.ts.net

# Should resolve to the M1's Tailscale IP
```

Use the **Magic DNS name**, never the raw IP (the IP can change after Wi-Fi roam).

## 5. Tag each machine

```bash
# M1
sudo tailscale up --advertise-tags=tag:m1

# Workstation
sudo tailscale up --advertise-tags=tag:station
```

In the [Tailscale admin console](https://login.tailscale.com/admin/machines), enable
"Use this key for tagging" for each machine.

## 6. ACL configuration

Go to the [Tailscale admin console](https://login.tailscale.com/admin/acls) → "Access Controls".

Replace the default with this:

```json
{
  // Personal AI Second Brain v4 ACL
  // Goal: allow only the right machines to talk to the right ports

  "acls": [
    // M1 → workstation
    {
      "action": "accept",
      "src": ["tag:m1"],
      "dst": ["tag:station:8080", "tag:station:6333"]
    },
    // Workstation → M1
    {
      "action": "accept",
      "src": ["tag:station"],
      "dst": ["tag:m1:11434", "tag:m1:6333", "tag:m1:8642"]
    },
    // Phone → M1 (chat UI only)
    {
      "action": "accept",
      "src": ["tag:phone"],
      "dst": ["tag:m1:3000"]
    },
    // Allow Tailscale's own services
    {
      "action": "accept",
      "src": ["*"],
      "dst": ["*:*"]
    }
  ],

  // Tag definitions
  "tagOwners": {
    "tag:m1": ["autogroup:admin"],
    "tag:station": ["autogroup:admin"],
    "tag:phone": ["autogroup:admin"]
  },

  // Optional: enable SSH through Tailscale
  "ssh": [
    {
      "action": "accept",
      "src": ["autogroup:admin"],
      "dst": ["autogroup:self"],
      "users": ["autogroup:nonroot"]
    }
  ]
}
```

Click "Save".

## 7. Verify ACLs

```bash
# From M1: should succeed
curl http://station:8080/v1/models

# From M1: should FAIL (port 11434 is M1's, not station's)
curl http://station:11434/v1/models

# From workstation: should succeed
curl http://m1:11434/v1/models

# From phone: should succeed (after installing Tailscale + opening browser)
# Open http://m1:3000 in browser

# From phone: should FAIL
curl http://m1:11434/v1/models
```

## 8. Headscale (optional OSS alternative)

If you want zero cloud dependency:

```bash
# On a separate machine (or Docker on workstation)
docker run -d \
  --name headscale \
  -v /var/lib/headscale:/var/lib/headscale \
  -p 8080:8080 \
  headscale/headscale:latest

# Configure each client to use your Headscale
sudo tailscale up --login-server https://your-headscale.example.com
```

Trade-off: ~2-4 hours of setup + maintenance; gain: zero cloud.

## 9. Magic DNS shortnames

Add short names to `/etc/hosts` (Linux) or `/private/etc/hosts` (macOS):

```
# /etc/hosts additions
100.x.x.x   m1
100.y.y.y   station
```

But **prefer Magic DNS** (`m1.tail-xxxx.ts.net`) so addresses survive
network changes.

## 10. Common gotchas

| Problem | Fix |
|---|---|
| `tailscale status` shows "Offline" | Check `sudo systemctl status tailscaled`; restart with `sudo systemctl restart tailscaled` |
| ACL changes not applied | Tailscale pushes ACLs within ~30s; check admin console for "Last update" timestamp |
| Magic DNS doesn't resolve | Enable Magic DNS in admin console → DNS |
| IP changes after Wi-Fi roam | Use Magic DNS names, never raw IPs |
| Headscale clock skew | `chronyc tracking` on Headscale server |

---

## See also

- [Phase 0 啟動手冊](../Phase_0_啟動手冊.md) — initial Tailscale setup
- [v4 master plan §16](../個人AI第二腦落地方案_v4.md) — network topology
- [架構B 開源組件整合表](../架構B_開源組件整合表.md) — Tailscale version pin

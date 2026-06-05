# Phase 0 啟動手冊 — Day 1 Bootstrap

> **Goal**: Both machines are reachable, software is installed, RAID is mounted.
> **Duration**: ~1 day
> **When**: As soon as both reference machines are physically available.

---

## 0.1 Pre-flight checklist

Before you start, confirm:

- [ ] M1 Air is in hand, charged, running macOS 14+ (Sonoma or later)
- [ ] Workstation is in hand, running Fedora 41 Workstation or Ubuntu 24.04 LTS
- [ ] RAID is configured and accessible from at least one machine
- [ ] You have admin (sudo) on both
- [ ] You have a Tailscale account (free at https://tailscale.com) OR are willing to use Headscale
- [ ] You have ~2 hours of focused time

## 0.2 M1 setup (macOS)

```bash
# 1. System updates
sudo softwareupdate -i -a

# 2. Install Homebrew (if not already)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 3. Install core tools
brew install python@3.11 git jq htop watch tree ripgrep

# 4. Install Xcode Command Line Tools (for Metal compilation)
xcode-select --install

# 5. Create ai-brain directory
mkdir -p ~/ai-brain/{venv,models,scripts,eval,launchd,hermes_config,logs,snapshots}
cd ~/ai-brain

# 6. Clone the repo
git clone https://github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent.git
ln -s ~/mnemosyne/{src,tests,docs,examples} .

# 7. Create Python venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 8. Install Tailscale
# Download from https://tailscale.com/download/mac
# Or: brew install --cask tailscale
# After install, sign in and note your Tailscale IP

# 9. Verify
which python3.11 git tailscale jq
```

## 0.3 Workstation setup (Linux)

### Fedora 41

```bash
# 1. System updates
sudo dnf update -y

# 2. Install core tools
sudo dnf install -y python3.11 python3.11-venv git jq htop watch tree ripgrep gcc gcc-c++ cmake make

# 3. Create ai-brain-station directory
mkdir -p ~/ai-brain-station/{venv,llama.cpp,models,scripts,systemd,logs}
cd ~/ai-brain-station

# 4. Clone the repo
git clone https://github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent.git
ln -s ~/mnemosyne/{src,tests,docs,examples} .

# 5. Create Python venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 6. Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up

# 7. Install Vulkan SDK
# See https://vulkan.lunarg.com/sdk/home#linux
sudo dnf install -y vulkan-tools vulkan-loader vulkan-headers vulkan-validation-layers mesa-vulkan-drivers

# 8. Verify
which python3.11 git tailscale jq cmake
vulkaninfo | head -20   # should show A770
```

### Ubuntu 24.04 (alternative)

```bash
# 1. System updates
sudo apt update && sudo apt upgrade -y

# 2. Install core tools
sudo apt install -y python3.11 python3.11-venv git jq htop watch tree ripgrep gcc g++ cmake make

# 3-6. (same as Fedora, substituting apt where needed)

# 7. Vulkan
sudo apt install -y vulkan-tools mesa-vulkan-drivers vulkan-validationlayers
```

## 0.4 Tailscale mesh verification

On **M1**:
```bash
tailscale status
# Should show both m1 and station as "online"

# Get the M1 Tailscale IP (e.g. 100.x.x.x)
tailscale ip -4

# Ping the workstation
ping station
# (or use the Tailscale Magic DNS name)
```

On **workstation**:
```bash
tailscale status
ping m1
```

✅ **Done when**: Both machines can ping each other by Magic DNS name.

## 0.5 RAID mount (optional but recommended)

If you have a RAID volume, mount it on both machines:

### macOS (M1)
```bash
# Create mount point
sudo mkdir -p /Volumes/RAID

# Mount via SMB or AFP
# (configure your NAS first; assume SMB share is //nas/AISecondBrain)
mount_smbfs //user@nas/AISecondBrain /Volumes/RAID
```

### Linux (workstation)
```bash
# Install cifs-utils
sudo dnf install -y cifs-utils   # or apt install cifs-utils

# Create mount point
sudo mkdir -p /mnt/raid

# Add to /etc/fstab for auto-mount
echo "//nas/AISecondBrain /mnt/raid cifs credentials=/etc/samba/creds,uid=1000,gid=1000 0 0" | sudo tee -a /etc/fstab
sudo mount -a

# Verify
ls /mnt/raid/
```

✅ **Done when**: Both machines can read/write the RAID.

## 0.6 Tailscale ACL setup

See [`Tailscale_私網設定指南.md`](Tailscale_私網設定指南.md) for full config.

Quick version (paste into Tailscale admin console → Access Controls):

```json
{
  "acls": [
    {"action": "accept", "src": ["tag:m1"], "dst": ["tag:station:8080", "tag:station:6333"]},
    {"action": "accept", "src": ["tag:station"], "dst": ["tag:m1:11434", "tag:m1:6333", "tag:m1:8642"]},
    {"action": "accept", "src": ["tag:phone"], "dst": ["tag:m1:3000"]}
  ],
  "tagOwners": {
    "tag:m1": ["autogroup:admin"],
    "tag:station": ["autogroup:admin"],
    "tag:phone": ["autogroup:admin"]
  }
}
```

Then on each machine, set its tag:
```bash
# M1
sudo tailscale up --advertise-tags=tag:m1

# Workstation
sudo tailscale up --advertise-tags=tag:station
```

## 0.7 Service binding convention

All services bind to **`127.0.0.1`** by default. Tailscale ACLs decide who can reach.

| Service | Port | Machine |
|---|---|---|
| Ollama | 11434 | M1 |
| llama-server | 8080 | Workstation |
| Qdrant | 6333 | M1 (workstation has mirror) |
| Hermes Agent | 8642 | M1 |
| Open WebUI | 3000 | M1 |

## 0.8 Pre-flight RAM/VRAM check

On M1:
```bash
vm_stat | head -5
# Pages free: 12345.  → multiply by 4096 → free RAM in bytes
# Should show ~3-4GB free when idle
```

On workstation:
```bash
free -h
# Should show ~45GB available

# Check A770 is visible
vulkaninfo | grep -A 3 "deviceName"
# Should show "Intel(R) Arc(TM) A770 Graphics"
```

## 0.9 Day 1 wrap-up

At the end of Phase 0, you should have:

- [ ] Tailscale up on both machines
- [ ] Both machines can ping each other
- [ ] Tailscale ACLs configured
- [ ] Python venv created on both
- [ ] Repo cloned on both
- [ ] RAID mounted on both (or skipped if not available)
- [ ] Vulkan working on workstation (or CPU fallback if not)
- [ ] macOS Xcode CLT installed (for Metal)
- [ ] All pre-flight checks pass

## 0.10 Troubleshooting

### Tailscale not connecting

```bash
# Restart
sudo tailscale down
sudo tailscale up

# Check logs
sudo journalctl -u tailscaled -f   # Linux
log show --predicate 'process == "tailscaled"' --last 1h   # macOS
```

### Vulkan not detected

```bash
# Check ICDs
ls /usr/share/vulkan/icd.d/   # Linux
# Should have a .json file pointing to Intel or AMD driver

# Test
vulkaninfo | head
# If "cannot find ICD", install driver:
sudo dnf install -y intel-vulkan-driver   # Fedora
sudo apt install -y mesa-vulkan-drivers intel-media-va-driver   # Ubuntu
```

### Python venv not creating

```bash
# Check Python version
python3 --version   # should be 3.11+

# If not, install
brew install python@3.11   # macOS
sudo dnf install -y python3.11   # Fedora
```

---

## Next phase

→ [`Phase_1_部署指南.md`](Phase_1_部署指南.md) — Service deployment

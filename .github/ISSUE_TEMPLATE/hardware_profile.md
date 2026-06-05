---
name: Hardware profile
about: Add support for a new hardware configuration
title: "[HW] Add profile: <description>"
labels: ["enhancement", "hardware-profile"]
assignees: []
---

## Hardware profile

**Edge machine (perception / NAS / edge agent)**
- Model: [e.g. MacBook Pro 14" M3 Pro 18GB]
- RAM: [e.g. 18GB]
- Storage: [e.g. 1TB]
- OS: [e.g. macOS 15.2]

**Heavy inference machine (optional)**
- Model: [e.g. custom build]
- CPU: [e.g. 7800X3D]
- RAM: [e.g. 64GB DDR5-6000]
- GPU: [e.g. RTX 4080 16GB]
- OS: [e.g. Fedora 41]

**Storage**
- Capacity: [e.g. 24TB RAID-Z2]
- Filesystem: [e.g. ZFS / btrfs-raid1 / ext4]

## What changed vs the reference plan

- [ ] Ollama Modelfile (link to PR)
- [ ] llama.cpp build flags (link to PR)
- [ ] launchd / systemd units (link to PR)
- [ ] Hermes Agent config (link to PR)
- [ ] RAM budget revised (link to PR)
- [ ] VRAM budget revised (link to PR)

## Validation

- [ ] All services start via `systemctl status` / `launchctl list`
- [ ] Phase 0 checklist completed (link to test log)
- [ ] 10-eval smoke test passed (paste results)
- [ ] Full 100-eval suite re-run (link to results)

## Notes

Anything else reviewers should know.

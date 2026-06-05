---
name: Bug report
about: Report something that doesn't work as the plan says
title: "[BUG] "
labels: ["bug", "needs-triage"]
assignees: []
---

## What happened

A clear and concise description of what the bug is.

## What the plan / doc said should happen

Quote the relevant section of the plan / doc / code.

## Steps to reproduce

1. ...
2. ...
3. ...

## Environment

- Machine: [M1 Air 8GB / M2 Pro 16GB / RTX 3060 12GB / RX 7900 XTX 24GB / other]
- OS: [macOS 14.x / Ubuntu 24.04 / Fedora 41 / other]
- Component: [Hermes Agent / Ollama / llama.cpp / Qdrant / Mnemosyne / Open WebUI / Tailscale / other]
- Component version: [e.g. llama.cpp b4567, Hermes Agent v0.x]
- Architecture: [A: single-machine / B: dual-machine]

## Logs / screenshots

If applicable, add screenshots or paste relevant log output.

## Did this break a v3 invariant?

- [ ] Named Vectors `text_vec(768) + image_vec(512)`
- [ ] Single worker indexer
- [ ] Memory never forgotten
- [ ] Never auto-move files
- [ ] Local-first only
- [ ] I don't know / not applicable

## Additional context

Anything else that might help.

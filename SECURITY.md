# Security Policy

## Our commitment

**Mnemosyne** (a personal AI second brain) is built around a
**privacy-by-construction** design — your data never leaves your hardware.
We take this seriously.

## Supported versions

| Version | Supported |
|---|:---:|
| v4 (Hermes Agent era) | ✅ |
| v3 (self-built FastAPI era) | ⚠️ best-effort |
| v2 and earlier | ❌ |

## Reporting a vulnerability

**Please do not file a public GitHub issue for security vulnerabilities.**

Open a GitHub Security Advisory:
<https://github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent/security/advisories/new>

Or open a private discussion via the GitHub "Security" tab.

We will acknowledge within 72 hours and aim to provide a fix or mitigation
within 30 days for critical issues, 90 days for non-critical.

## Threat model

The system is designed against these adversaries:

- **Passive network observer on the same LAN** — mitigated by Tailscale
  encrypted mesh + 127.0.0.1 binding on all services
- **Compromised cloud AI provider** — N/A: no cloud AI is used
- **Malicious file in inbox** — mitigated by:
  - never-auto-move-files invariant
  - Qdrant payload-based access control
  - Tailscale ACLs (see `src/tailscale/`)
- **Stolen laptop while running** — mitigated by:
  - FileVault / LUKS on the host OS
  - RAM-only API keys (Tailscale pre-auth keys rotated every 90 days)

## What we will NOT fix

- Issues in upstream components (Hermes Agent, Mnemosyne, Qdrant, llama.cpp).
  Please report them to the upstream maintainer.
- Issues arising from users disabling the local-only invariant
  (e.g. exposing ports publicly).

## Cryptographic choices

- **Transport**: Tailscale WireGuard (Curve25519, ChaCha20-Poly1305)
- **At rest**: relies on host OS encryption (FileVault / LUKS)
- **API tokens**: stored in OS keychain via `security` (macOS) or
  `secret-tool` (Linux) — never in plaintext config files

## Out of scope

- Jailbreaking or running on untrusted hosts
- Multi-tenant deployments
- Federated setups with multiple users

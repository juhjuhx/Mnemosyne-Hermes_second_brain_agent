# DIT 2.2 Developer TUI — Design & Mockup Guide (DESIGN PREVIEW)

> **Status: NOT IMPLEMENTED.** This document defines the terminal-interface
> concept for a future developer TUI. It contains **no working TUI code**.
> All mockups are **CONCEPT MOCKUPS** generated from static, synthetic
> fixture data and must remain prominently labeled as such in any public
> material. They must not be presented as screenshots of a running product.
>
> **The only terminal capture in this release is the REAL EXECUTION output
> of the synthetic demo** (`python examples/dit22_synthetic_demo.py`,
> captured in `dit22-demo-real-exec.txt`), which is reproducible from the
> repo.

## Why a design document, not a build

The §7 boundary in the engineering prompt is explicit: *do not turn the
documentation/visual task into an uncontrolled UI rewrite*. A real
interactive TUI (Textual or equivalent) is a separate development effort
gated by approval. This document scopes that effort so the eventual build
is controlled.

## Design system (single concept, consistent across 6 screens)

| Element | Rule |
|---|---|
| Header | Project name + branch/state line + test status (`330 tests · green` only when the battery has been run this session) |
| Navigation | Screen list: `overview ▸ ingest ▸ jobs ▸ media ▸ ai ▸ hw` |
| Job state | `PUBLISHED / PENDING / QUARANTINE / retry n/m backoff Xs` — always from `reconcile_proxy_job` verdicts, never inferred |
| Asset identity | `asset sha256 … · camera family …` (family is `unverified` unless provenance evidence says otherwise) |
| Replica evidence | replica id + storage + verified flag + PASS/FAIL read-back |
| Proxy queue | lease-fenced rows; stale staging noted as swept-on-live-success |
| Media metadata | ffprobe facts (FPS, timecode, HDR, audio layout) with `unknown` shown as such |
| Scene detection | provider + segment counts; `neural_model_used: false` for CPU providers |
| Recovery log | read-only issue list with `safe_action` per issue — never shows a delete as performed |
| Storage pressure | used/free bar + the **advisory 15%** line, explicitly labeled advisory |
| AI services | Track A services listed with `hardware-pending` state; no invented "running" state |
| Hardware-blocked indicators | A770 GPU / UNC-SMB / SD camera card always shown as `HARDWARE BLOCKED` or `UNVERIFIED` until physical evidence exists |
| Human approval actions | danger actions follow `read-only → plan → approve → execute`; the TUI shows approval prompts, and the underlying gate refuses anything not approved |

### Minimum screens (the 6 in the prompt)

- **A. Overview Dashboard** — state, test status, storage pressure, hardware indicators.
- **B. DIT Ingest / Archive Evidence** — admission verdicts, replica + evidence ledger rows.
- **C. Proxy Jobs / Recovery** — job state, retry budget, read-only recovery verdicts.
- **D. Media Library / Scene Detection** — probe facts + CPU scene segments.
- **E. AI Indexing & Search** — **labeled FUTURE / EXPERIMENTAL** (Track A integration is hardware-pending; no live search UI exists).
- **F. Hardware / Storage Diagnostics** — census-style read-outs; any value that has not been physically collected shows `NOT COLLECTED`, not a number.

### Mockup provenance rule

The dashboard mockup asset (`docs/assets/rc1/tui-dashboard-concept.svg` /
`.png`) is built from **static fixture values only** and carries the
`DESIGN PREVIEW` / `CONCEPT MOCKUP` watermark in the artwork itself. Any
future real capture must be a verbatim program output, never hand-drawn.

## Evolving the current CLI into a proper TUI (documented path, no coupling to storage-mutation permissions)

1. **Keep the CLI surface pure-read for all state screens.** The TUI
   renderer reads the same objects the tests already use:
   `reconcile_proxy_job` reports, `MediaProbe` results, queue rows,
   catalog evidence. No renderer may import a mutation API.
2. **Mutation commands (future) stay behind the existing gates.** A TUI
   "action" (e.g. `complete_rename`, retry a job) is only a *proposal*
   that calls the same fail-closed gate functions (`job_queue.retry`,
   capacity gate, admission) — the TUI adds no new code path that can
   write. Visual components never gain storage-mutation permissions of
   their own.
3. **Framework choice is deferred to the build phase.** Textual (or an
   equivalent) is a candidate, not a decision; the design above is
   framework-neutral (headers, screens, verdicts, approval prompts).
4. **Gating**: implementing the TUI is its own slice requiring the same
   TDD + independent-review discipline (Red→Green, focused/full battery,
   ruff, negative tests for every "action" button proving the underlying
   gate denies without approval).

## Public-presentation rules

- Label every mockup **DESIGN PREVIEW / CONCEPT MOCKUP**.
- The REAL EXECUTION capture (demo stdout) is the only terminal artifact
  allowed without that label, and it must be reproducible from the repo.
- No fabricated real-world status, no invented job rows, no real
  footage, no absolute host paths.

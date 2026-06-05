# 07_更新日誌 — Phase-End Summaries

> This folder is reserved for **phase-end summaries** that the canonical
> `../CHANGELOG.md` (in repo root) is too detailed to capture.

## What goes here

| File pattern | Purpose |
|---|---|
| `phase{N}-end-{YYYY-MM-DD}.md` | One per completed phase; what was achieved, what changed vs plan, what was deferred |
| `year-end-{YYYY}.md` | Annual summary (every Dec 31) |
| `hotfix-{YYYY-MM-DD}-{SHORT}.md` | Emergency fix retrospective |

## Why a separate folder?

The root `CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/)
format — bullet points, semver-tagged, machine-parseable. That's great
for tooling but loses the *narrative*:

- Why did Phase 2 take 5 days instead of 3-4?
- What surprised us about MTP speculative decoding on A770?
- Which 3 risks materialized and how did we respond?
- Which 2 risks we accepted did NOT materialize?

Those stories go here, in free-form markdown.

## Template

```markdown
# Phase N end — YYYY-MM-DD

**Status**: Complete (or Partial: X/Y deliverables)
**Tag**: v4.X.Y-YYYY-MM-DD-phaseN
**Duration**: X days (planned: Y days)

## What was delivered

- [x] Deliverable 1
- [x] Deliverable 2
- [ ] Deliverable 3 (deferred to Phase N+1)

## What surprised us

- Insight 1
- Insight 2

## Risks materialized

| Risk ID | What happened | Mitigation | Status |
|---|---|---|---|
| R07 | Backup cron failed silently for 3 days | Added watchdog; now exits 1 on failure | Resolved |

## Risks that did NOT materialize

- R13 (8GB RAM): we ended up with 1.5GB headroom, not 1GB
- R18 (Qwen3.6 license): verified Apache 2.0 + acceptable use policy

## Carried forward to next phase

- Q01 (M1 Hermes mode): still TBD; A/B test in Phase 4
- Q04 (27B vs 35B-A3B): chose 27B as primary, 35B as backup; revisit at 1TB of indexed data
```

## See also

- [`../../../CHANGELOG.md`](../../CHANGELOG.md) — canonical changelog
- [`../../06_備份與同步/版本標籤規範.md`](../06_備份與同步/版本標籤規範.md) — tag conventions
- [`../../02_方案文檔/Phase_*_*.md`](../02_方案文檔/) — the phase plans

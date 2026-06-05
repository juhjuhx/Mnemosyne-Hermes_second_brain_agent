# AGENTS.md — Mnemosyne

> **Read this first** if you are an AI agent, future-me, or new contributor
> picking up this repo. This is the **operational** entry point — exact
> commands, current CI state, and gotchas. For the conceptual / architectural
> entry point (invariants, hardware, stack), see
> [`docs/02_方案文檔/AGENTS.md`](docs/02_方案文檔/AGENTS.md). Read both.

---

## What this repo is

**Mnemosyne v4** — a *plan-freeze* snapshot (frozen 2026-06-05) of a
dual-machine local-first personal AI second brain. The plan is complete
on paper; the **two reference machines were offline during planning**, so
most components are ⏳ pending physical deployment. Do **not** assume any
service is running. All services bind to `127.0.0.1` and run on user-owned
hardware. Nothing leaves the LAN.

- **M1 Air 8GB / 256GB / Metal** — perception, NAS, edge agent, Hermes host.
- **Workstation 5800X / 48GB / A770 16GB / Vulkan** — heavy inference.

---

## The 7 unbreakable invariants

If a change appears to break one, **stop and ask the user** before
proceeding. These are enforced in code and tested.

1. **Qdrant Named Vectors** — `text_vec(768) + image_vec(512)` per point.
   Changing dimensionality forces a full re-index.
2. **Single worker indexer** — `src/scripts/indexer.py:53` raises
   `ValueError("workers must be 1 (v3 invariant)")` if `workers != 1`.
   Parallelism is OK at the *embedding* step (one file → N chunks → batch
   embed), **not** at the *file* step.
3. **Memory never forgotten** — original files are the source of truth;
   the Qdrant + Mnemosyne + SQLite index is a *derived view* and is
   rebuildable. If the index is wrong, fix the index, never the source.
4. **Never auto-move files** — the indexer writes a `suggested_move`
   payload field. The UI prompts; the indexer never mutates the archive.
5. **No facial / voice-emotion monitoring** — biometric identification
   is out of scope. STT is fine; emotion inference is not.
6. **Local-first AI only** — no cloud LLM, embedding, or STT. Network is
   Tailscale mesh + LAN only.
7. **8 GB RAM hard limit on M1** — the whole M1 service stack must fit
   in ~7.5 GB peak.

**Invariant tests** (will fail loudly if you break any of the above):
- `tests/test_index_pipeline.py::test_config_rejects_workers_greater_than_one`
- `tests/test_qdrant_named_vectors.py::test_indexer_uses_text_vec_named_vector`
- `tests/test_index_pipeline.py::test_indexer_records_suggested_move_never_moves`

---

## Commands

All commands are run from the **repo root**.

### Tests

```bash
# Install deps (one-time; matches CI). pyproject.toml is the source of truth.
pip install -e .

# Run the full unit + integration suite (no live Qdrant/Ollama required)
pytest tests/ -v

# Run only the fast unit tests (skip subprocess integration)
pytest tests/ -v -m "not integration"

# Run only the MCP stdio integration tests
pytest tests/test_hermes_skills.py -v
pytest tests/test_mcp_servers.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

### Lint / typecheck (matches CI)

```bash
# Python
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/ tests/        # CI is warnings-only today

# Shell
shellcheck src/scripts/*.sh
```

### Verify the v4 plan snapshot

```bash
python3 _archive/2026-06-05-v4-plan/verify.py .
# Expected: 105 OK, 0 CHANGED, 0 MISSING
# Exit 0 = all 105 tracked files match the SHA-256 manifest.
```

### Run the indexer (dry-run, writes nothing)

```bash
python src/scripts/indexer.py --config examples/indexer_config.yaml --dry-run
```

### Run the eval set against a live Hermes

```bash
python src/scripts/eval_runner.py \
    --eval-set tests/eval_v2_100.jsonl \
    --hermes-url http://127.0.0.1:8642 \
    --output tests/_results/$(date +%Y-%m-%d).json
```

### Backup (RAID + OneDrive layers)

```bash
# From M1: L0/L1 → L2 (RAID)
bash docs/06_備份與同步/sync_raid.sh

# From workstation: L2 → L3 (OneDrive + rclone crypt)
bash docs/06_備份與同步/sync_onedrive.sh
```

---

## Repository layout

```
.
├── AGENTS.md                            ← you are here (operational)
├── LICENSE, LICENSE-DOCS                ← AGPL-3.0 (code) / CC BY-SA 4.0 (docs)
├── pyproject.toml                       ← Python project metadata + deps (editable install)
├── .yamllint.yml                        ← yamllint config (strict-mode safe)
├── lychee.toml                          ← lychee link checker config (excludes RFC 2606 placeholders)
├── CHANGELOG.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
├── docs/
│   ├── 00_index.md                      ← master TOC, every artifact
│   ├── 01_對話與調研紀錄/                ← 8 research logs (READ for context)
│   ├── 02_方案文檔/AGENTS.md            ← conceptual entry (invariants, stack)
│   ├── 02_方案文檔/個人AI第二腦落地方案_v4.md  ← the 27-section master plan
│   ├── 02_方案文檔/Phase_0..5_*.md      ← phase guides (start at Phase 0)
│   ├── 03_架構圖_SVG/                    ← 11 hand-crafted dark SVGs
│   ├── 06_備份與同步/                    ← sync_raid.sh, sync_onedrive.sh
│   └── 07_更新日誌/                      ← phase-end summaries (reserved)
├── src/
│   ├── scripts/                         ← indexer.py, eval_runner.py, ...
│   ├── hermes_skills/                   ← 3 MCP skills (qdrant / filesystem / video-slice)
│   ├── launchd/                         ← 6 macOS plists
│   ├── systemd/                         ← 3 Linux units
│   ├── tailscale/                       ← ACLs
│   ├── ollama/                          ← Modelfiles
│   └── llama_cpp/                       ← build flags + RPC config
├── tests/                               ← eval_v2_100.jsonl (100 entries) + 4 test_*.py
├── examples/                            ← sample YAML configs
├── .github/                             ← CI workflows + 5 issue / 1 PR template
└── _archive/2026-06-05-v4-plan/         ← SHA-256 snapshot (105 files)
```

---

## Known issues / gotchas

- **License is AGPL-3.0-or-later, not MIT.** `LICENSE` is the FSF AGPL v3
  text with `# SPDX-License-Identifier: AGPL-3.0-or-later` header. All 3
  skill `manifest.json` files, `README.md`, `CONTRIBUTING.md`, and
  `docs/00_index.md` have been updated to match. Historical entries in
  `CHANGELOG.md` and `docs/01_對話與調研紀錄/` still reference MIT — that
  is correct (v3 snapshot was MIT; v4 changed to AGPL-3.0). AGPL-3.0
  closes the SaaS loophole — Section 13 requires offering Corresponding
  Source to all users if offered as a remote service.
- **`pyproject.toml` exists.** CI runs `pip install -e .` (`ci.yml:78`);
  it installs deps from `tests/requirements.txt`. The `packages = []`
  setting means no actual code is installed; tests use `conftest.py`
  sys.path injection instead of `__init__.py`.
- **`.yamllint.yml` exists.** CI's `lint-yaml` job uses it with
  `strict: true`. It disables `line-length`, `document-start`, and
  loosens `truthy` for GitHub Actions `on:` keys. The `examples/` dir
  is excluded (YAML inside markdown code fences).
- **`lychee.toml` exists.** The `markdown-link-check` workflow uses
  `lychee-action@v2` which downloads lychee v0.23.0. This version has
  breaking CLI changes: `--exclude-mail` was removed (use
  `--exclude '^mailto:.*'`), `--accept` cannot be repeated (use
  `accept = [...]` in toml). All config is in `lychee.toml`; the
  workflow only passes `--offline docs/ README.md`.
- **`structure-check.yml` line 28** checks for `tests/eval_v2_100.jsonl`
  (not `.md`). This is correct as of the CI fix commit.
- **URLs point to the user's fork** `github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent`
  (in `README.md`, `CHANGELOG.md`, `SECURITY.md`, `Phase_0_啟動手冊.md`,
  `還原演練.md`, `src/systemd/*.service`). If you fork, search-replace
  `juhjuhx/Mnemosyne-Hermes_second_brain_agent` → `<your>/<your-repo>`
  across the same set of files.
- **Upper folder name** `Hermes_second_brain_agent_AIIinONE/` is the
  user's working-directory name and is **kept on purpose**. The
  canonical GitHub repo is `github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent`;
  the deployed path on either machine is `~/mnemosyne/` (cloned with
  `git clone https://github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent.git ~/mnemosyne`).
  Do not rename the upper folder without asking.
- **SVGs are hand-crafted.** The `baoyu-diagram` skill was loaded but
  not used; the 11 diagrams in `docs/03_架構圖_SVG/` were edited by
  hand for determinism. Don't invoke `baoyu-diagram` to "regenerate"
  them — edit the SVG directly.
- **Chinese filenames** under `docs/01_對話與調研紀錄/` and
  `docs/02_方案文檔/` are intentional and render fine on GitHub. The
  structure-check only warns on `<>:"\|?*` chars.
- **Two config locations** for the indexer: `examples/indexer_config.yaml`
  is the in-repo sample; the real deployed config lives at
  `~/ai-brain-station/index/indexer_config.yaml` on M1 (see
  `Phase_0_啟動手冊.md`).
- **MCP protocol version** is `2024-11-05`. Skill `serverInfo.name` is
  `qdrant-search` / `filesystem-search` / `video-slice` — the
  `test_all_skills_initialize` test pins these names.
- **WSL credential handling.** The first `git push` from a fresh WSL
  session requires entering the PAT at the git prompt (username
  `juhjuhx`, password = fine-grained PAT). `credential.helper=store`
  saves it to `~/.git-credentials` for subsequent pushes. If pushing
  fails with "Password authentication not supported", the PAT was not
  saved — re-enter it. PATs expire in 90 days; rotate at
  `https://github.com/settings/tokens?type=beta`.

---

## Reading order for a new agent

1. **This file** — operational commands + gotchas.
2. **`docs/02_方案文檔/AGENTS.md`** — the 7 invariants, hardware, stack table.
3. **`docs/02_方案文檔/個人AI第二腦落地方案_v4.md`** — the 27-section master plan.
4. **`docs/02_方案文檔/Phase_0_啟動手冊.md`** — day-1 bootstrap checklist.
5. **`docs/00_index.md`** — full table of contents.
6. **`_archive/2026-06-05-v4-plan/CHANGELOG.md`** — what was new in v4 vs v3.

---

## Style conventions

- User-facing prose: **Traditional Chinese (繁體中文)**.
- Code, identifiers, CLI, docstrings, comments: **English**.
- Structured data goes in markdown tables.
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/).
- Tests: pytest, fixtures from `tests/conftest.py` (`tmp_dir`,
  `sample_text_file`, `sample_image_file`, `fake_ollama_embedding`,
  `in_memory_qdrant`).
- Add an entry to `CHANGELOG.md` `[Unreleased]` for any user-visible
  change.

---

## Workflow for any change

1. Re-read the relevant invariant above before editing code.
2. Edit the file. Keep changes scoped; do not reformat unrelated code.
3. Run the test command for the area you touched:
   - `pytest tests/ -v` for anything in `src/`
   - `python3 _archive/2026-06-05-v4-plan/verify.py .` if you changed
     the manifest (it is frozen — only the *next* archive snapshot may
     add new entries; do not edit the 2026-06-05 manifest in place).
4. Run the lint commands for the area you touched.
5. Update `CHANGELOG.md` `[Unreleased]` if user-visible.
6. If unsure: **ask the user**. The cost of a clarifying question is
   far less than the cost of breaking an invariant.

---

*"Memory never forgotten. The original file is the source of truth; the index is a derived view."*

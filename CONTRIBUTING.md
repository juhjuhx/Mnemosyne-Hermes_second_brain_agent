# Contributing to Personal AI Second Brain (Hermes Edition)

Thank you for considering a contribution! This project is a **parameterized
blueprint**, not a single-user tool. The more hardware profiles and use cases
we cover, the more useful it becomes.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you are expected to uphold this code.

## How to contribute

### 1. Add a new hardware profile

The reference plan targets an M1 Air 8GB + Linux workstation with A770 16GB.
If you have validated the plan on a different setup, please add:

- A new entry in `docs/02_方案文檔/架構B_開源組件整合表.md` "Supported Hardware" section
- Any tweaks needed to Modelfiles, systemd units, or llama.cpp build flags
- Notes on what you had to change and why

Common alternative profiles we want to cover:

| Profile | Status |
|---|---|
| M1 Air 8GB + RTX 3060 12GB workstation | wanted |
| M2 Pro 16GB + RX 7900 XTX 24GB | wanted |
| M3 Max 64GB single-machine (architecture A) | wanted |
| Steam Deck OLED + NAS (different topology) | wanted |

### 2. Add a new Hermes skill

Skill templates live in `src/hermes_skills/`. To add one:

1. Create `src/hermes_skills/<skill-name>/`
2. Include:
   - `SKILL.md` — frontmatter (name + description) + usage instructions
   - `manifest.json` — MCP server config, tools exposed, dependencies
   - `tests.py` — pytest suite for the skill
   - `README.md` — quick example
3. Follow the [Agent Skills](https://agentskills.io) specification
4. Update `docs/02_方案文檔/Hermes_Skill_範本庫.md` to reference the new skill

### 3. Improve the evaluation suite

The 100-entry eval set in `tests/eval_v2_100.md` is the v4 ground truth. We
welcome:

- New query categories
- New ground-truth annotations
- New metric implementations in `tests/`
- Automated eval runners (e.g. RAGAS, deepeval integration)

### 4. Fix documentation

- Typos, broken links, unclear diagrams
- Translation to other languages (especially Traditional Chinese, which is
  the primary working language)
- More architecture diagrams (we have 8-10, but always want more)

## Pull request process

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-skill`)
3. Make your changes
4. Run the test suite (`pytest tests/`)
5. Update `CHANGELOG.md` under `[Unreleased]`
6. Submit a PR with a clear description of what & why
7. Wait for review

## Commit message convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(skills): add Notion connector skill
fix(qdrant): snapshot script now handles 0-byte collections
docs(plan): clarify Phase 2.3 worker queue semantics
chore: bump llama.cpp to b4567
```

## License

By contributing, you agree that:

- Your **code** contributions are licensed under AGPL-3.0 ([`LICENSE`](LICENSE))
- Your **documentation** contributions are licensed under CC BY-SA 4.0 ([`LICENSE-DOCS`](LICENSE-DOCS))

## Reporting bugs / requesting features

Please use the GitHub issue templates in `.github/ISSUE_TEMPLATE/`.
For security issues, see [`SECURITY.md`](SECURITY.md).

# Examples

Sample configurations and templates. Copy and adapt to your environment.

## What's in here

```
examples/
├── hermes_config.yaml       Sample Hermes Agent config (skills, MCP servers, model aliasing)
├── indexer_config.yaml      Sample indexer config (inbox, archive, workers, qdrant/ollama URLs)
├── tailscale_setup.md       Step-by-step Tailscale mesh setup for the dual-machine topology
├── skill_template/          Bare-bones Hermes skill (copy and rename to start a new skill)
└── eval_result_sample.json  Sample output of `eval_runner.py` (one good run, one failed run)
```

## How to use

1. **Config samples** (the `.yaml` and `.md` files): copy to your
   `~/ai-brain-station/hermes_config/` (M1) or
   `~/ai-brain-station-station/hermes_config/` (workstation) and
   edit the values for your environment.

2. **Skill template** (`skill_template/`): copy to
   `src/hermes_skills/my-new-skill/` and follow the agentskills.io spec.

3. **Eval result** (`eval_result_sample.json`): reference for what a
   well-formed eval run output looks like. Use as a test fixture for
   the eval results dashboard (Phase 4 expansion).

## See also

- [`../docs/02_方案文檔/Hermes_Skill_範本庫.md`](../docs/02_方案文檔/Hermes_Skill_範本庫.md) — skill template catalog (3 worked examples)
- [`../docs/02_方案文檔/Phase_1_部署指南.md`](../docs/02_方案文檔/Phase_1_部署指南.md) — Phase 1 service deployment
- [`../src/hermes_skills/`](../src/hermes_skills/) — 3 fully-worked skills

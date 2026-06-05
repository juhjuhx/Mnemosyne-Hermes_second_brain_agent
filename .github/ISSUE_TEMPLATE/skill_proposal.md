---
name: Hermes skill proposal
about: Propose a new skill for the Hermes Agent skill library
title: "[SKILL] "
labels: ["enhancement", "skill"]
assignees: []
---

## Skill name

`<verb>-<object>` (e.g. `transcribe-audio`, `summarize-video`, `tag-photo`)

## What does it do?

One-paragraph description.

## What tools does it expose?

- `tool_1`: <input schema> → <output schema>
- `tool_2`: ...

## What dependencies does it need?

- [ ] No new dependencies
- [ ] Python packages: `<list>`
- [ ] System packages: `<list>`
- [ ] External services: `<list>`

## Skill template

Will follow `src/hermes_skills/<skill-name>/` layout with:
- [ ] `SKILL.md` (frontmatter + instructions)
- [ ] `manifest.json` (MCP server config)
- [ ] `tests.py` (pytest)
- [ ] `README.md` (quick example)

## Which v4 plan phase does it serve?

- [ ] Phase 0 (bootstrap)
- [ ] Phase 1 (service deployment)
- [ ] Phase 2 (indexing)
- [ ] Phase 3 (Hermes integration)
- [ ] Phase 4 (eval & feedback)
- [ ] Phase 5 (advanced)

## Test plan

How will we know it works?

## Open questions

Anything unresolved.

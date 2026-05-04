# Agent Label Taxonomy — Punta Scraper

The canonical definition of agent labels and their lifecycle lives in [`../../../agent-coding-rules/rules/issue-management.md`](../../../agent-coding-rules/rules/issue-management.md) §2. This file records the Punta Scraper-specific colour scheme only.

## Punta Scraper label colours

| Label | Color | Source | Purpose |
|-------|-------|--------|---------|
| `bug` | Red (`#D73A4A`) | human or triage | Defect or regression |
| `enhancement` | Light blue (`#A2EEEF`) | human or triage | New feature or behaviour |
| `performance` | Yellow (`#FBCA04`) | human or triage | Slowness, memory, resource use |
| `investigation` | Grey (`#BFDADC`) | human or triage | Research before any code |
| `ci-failure` | Dark red (`#B60205`) | triage | Auto-filed by triage when main is broken |
| `approved` | Green (`#0E8A16`) | **human only** | Plan reviewed and approved |
| `rejected` | Black (`#000000`) | **human only** | Closed without implementing |
| `agent:needs-triage` | Grey (`#CCCCCC`) | agent | Issue unclear |
| `agent:request-screening` | Yellow-green (`#C5DEF5`) | agent | Awaiting human screening |
| `agent:plan-review` | Purple (`#D4C5F9`) | agent | Plan posted, awaiting human review |
| `agent:in-progress` | Orange (`#FFA500`) | agent | Actively working on it |
| `agent:pr-open` | Blue (`#1D76DB`) | agent | PR opened for this issue |
| `agent:blocked` | Dark red (`#B60205`) | agent | Work paused on dependency |
| `needs-human` | Red (`#D93F0B`) | agent | Too complex/risky for agents |

## Lifecycle

See [`issue-management.md`](../../../agent-coding-rules/rules/issue-management.md) §2.2 (the `agent:*` protocol labels) and §2.3 (what agents may / may not do with labels). The key rules:

- Only **one** `agent:*` label at a time (per [`github-posting-rules.md`](../../../agent-coding-rules/rules/github-posting-rules.md) §4).
- `approved` and `rejected` are **human-only** — an agent never applies them.
- An `agent:*` label change must be accompanied by a comment explaining the state change (per `github-posting-rules.md` §2).
- Stale `agent:in-progress` (>2h without update) is cleaned up by the multi-repo triage agent (hosted in Switchboard) per `development-workflow.md` §10.

## Creating missing labels

If any of the labels above are missing on the repo, create them:

```bash
MSYS_NO_PATHCONV=1 gh label create "<name>" --color "<hex>" --description "<purpose>"
```

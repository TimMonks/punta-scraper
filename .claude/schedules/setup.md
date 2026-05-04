# Schedule Setup and Reinstatement

Source of truth for the scheduled tasks this repo expects to have running. If they're lost (new VM, host rebuild, accidental deletion), recreate them by following this file.

## Layout

Every `.md` file in `.claude/schedules/` describes one registerable scheduled task, **except**:

- `setup.md` — this file (orchestration only)
- `labels.md` — GitHub label taxonomy (prerequisite, not a schedule)

To enumerate the schedule files:

```bash
ls .claude/schedules/*.md | grep -vE '/(setup|labels)\.md$'
```

Each schedule file declares:

- **Cron** — the schedule expression
- **Task ID** — the global registration ID (per-repo tasks use `<task>-<repo-slug>` to avoid collision when several repos register on one host).
- **Prompt source of truth** — the agent file in `.claude/agents/` whose contents are copied verbatim into the registered task at registration time.

## Prerequisites

The GitHub labels defined in [`labels.md`](labels.md) must exist on the repo. Create any missing labels with:

```bash
MSYS_NO_PATHCONV=1 gh label create "<name>" --color "<hex>" --description "<purpose>"
```

Colours and descriptions are in [`labels.md`](labels.md); taxonomy is defined in [`../../../agent-coding-rules/rules/issue-management.md`](../../../agent-coding-rules/rules/issue-management.md) §2.

## Reinstatement steps

1. Open a Claude Code session in this repo's directory.
2. Ask Claude: **"Please reinstate the agent schedules from `.claude/schedules/`."**

   The expected agent behaviour is:
   - Read every `.md` file under `.claude/schedules/` except `setup.md` and `labels.md`.
   - For each: register a scheduled task using the `cronExpression`, `description`, and the **verbatim contents** of the prompt source file (`.claude/agents/<task-id>.md`).
   - Use the Task ID from each schedule file as-is.
   - Verify with: list scheduled tasks.

3. Confirm the listed tasks match the schedule files.

## Monitoring

- Scheduled task status: list scheduled tasks (or `mcp__scheduled-tasks__list_scheduled_tasks`).
- Issue label state: `MSYS_NO_PATHCONV=1 gh issue list --state open --json number,title,labels`.
- Stale locks: `MSYS_NO_PATHCONV=1 gh issue list --state open --label "agent:in-progress"`.
- Open agent PRs: `MSYS_NO_PATHCONV=1 gh pr list --state open`.

## Disabling

To pause all automation:

1. Disable each registered scheduled task (one per schedule file).
2. Optionally: remove `agent:in-progress` labels from any claimed issues.

## Editing prompts

The scheduled task is registered with a **snapshot** of the agent prompt at registration time. When you edit `.claude/agents/<task-id>.md`, the running task does not pick up the change until you re-register it (delete + create, or update via `mcp__scheduled-tasks__update_scheduled_task`).

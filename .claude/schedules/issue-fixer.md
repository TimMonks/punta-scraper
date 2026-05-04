# Issue Fixer — Punta Scraper

## Schedule

- **Cron**: `*/10 * * * *` (every 10 minutes)
- **Task ID**: `issue-fixer-punta-scraper`

## Prompt source of truth

The prompt this scheduled task runs is [`.claude/agents/issue-fixer.md`](../agents/issue-fixer.md). Edit that file; re-register the schedule when the prompt changes.

That agent file in turn references the shared rules in [`../../../agent-coding-rules/rules/`](../../../agent-coding-rules/rules/) — notably `agent-startup.md`, `issue-management.md`, `pr-management.md`, `development-workflow.md`, `github-posting-rules.md`, `triage-rules.md`, `issue-closing-rules.md`.

## Registering the task

Use the Claude Code `schedule` skill (or the `mcp__scheduled-tasks__create_scheduled_task` MCP tool):

- **Task ID**: `issue-fixer-punta-scraper`
- **Cron**: `*/10 * * * *`
- **Description**: "Picks up open Punta Scraper issues, fixes simple ones, writes plans for complex ones."
- **Prompt**: contents of `.claude/agents/issue-fixer.md` (copied verbatim into the scheduled task).

Verify after registering: list scheduled tasks.

## Monitoring

- Scheduled task status: list scheduled tasks.
- Issue label state: `MSYS_NO_PATHCONV=1 gh issue list --state open --json number,title,labels`.
- Stale locks: `MSYS_NO_PATHCONV=1 gh issue list --state open --label "agent:in-progress"`.
- Open agent PRs: `MSYS_NO_PATHCONV=1 gh pr list --state open`.

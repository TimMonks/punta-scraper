---
name: issue-fixer
description: Retired pointer. The issue fixer for Tim's personal repos, punta-scraper included, is defined in Folio's .claude/agents/issue-fixer.md, runs from Folio's daily folio-issue-fixer scheduled task, and never merges.
---

# Issue Fixer — retired here, see Folio

Since 2026-09-30 one issue fixer works all of Tim's personal repos, `punta-scraper` included ([Folio#7670](https://github.com/TimMonks/Folio/issues/7670)). It lives in Folio and is PR-only: it raises a PR per issue and never merges. Folio's release manager merges this repo through its row in [`repo-profiles.md`](../../../Folio/.claude/agents/release-manager/repo-profiles.md).

- **Definition:** [`Folio/.claude/agents/issue-fixer.md`](../../../Folio/.claude/agents/issue-fixer.md)
- **Scope and per-repo rules:** [`Folio/.claude/agents/issue-fixer/repo-scope.md`](../../../Folio/.claude/agents/issue-fixer/repo-scope.md)
- **Scheduled task:** Folio's `folio-issue-fixer`. Do not register a separate issue-fixer task for this repo.

If you were dispatched as this agent, read the Folio definition from its `origin/main` and follow it, scoped to this repo.

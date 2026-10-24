> ⛔ **ONE TASK PER INVOCATION** — Complete one task from @.agent/tasks.json, commit, output `<promise>TASK-{ID}:DONE</promise>`, and STOP. Do NOT start the next task. Do NOT use parallel agents for multiple tasks.

## Overview

You are working on the Automated Multi-Asset Trading System (AMATS) described in @.agent/prd/SUMMARY.md and @docs/PRD.md.

## Required Setup

Environment runs Python 3.11 with virtualenv at `./venv`.
FastAPI Brain API runs at `http://localhost:8000`.

## Before Starting

Check @.agent/STEERING.md for critical work. Complete items in sequence, remove when done. Only proceed to implement tasks if no critical work pending.

## Task Flow

Tasks are listed in @.agent/tasks.json

1. Pick highest-priority task with `passes: false` in `tasks.json`
2. Read full spec: `.agent/tasks/TASK-${ID}.json`
3. Check existing project structure in @README.md
4. Implement step-by-step according to spec and write unit test in `tests/` or component test directories.
5. Run test suite:
   ```bash
   ./venv/bin/pytest -v
   ```
6. All tests must pass. If any test fails, fix it before proceeding.
7. When tests pass, set `passes: true` in `tasks.json` for the task you completed.
8. Log entry → `.agent/logs/LOG.md` (date, brief summary, newest at the top).
9. Commit changes using Conventional Commit format (`git commit -m "..."`).

## Rules

- **CRITICAL**: Only work on **ONE task per invocation**. After committing the task, output `<promise>TASK-{ID}:DONE</promise>` and **STOP immediately**. Do NOT read the next task. Do NOT continue working. Your response **must END** after the promise tag. Any output after it is a violation.
- Kill any background processes (servers, test processes) before outputting the promise tag.
- Work only on the session branch `arena/b657ea09-forex-crypto`.
- **CRITICAL**: When **ALL** tasks pass → output `<promise>COMPLETE</promise>` and **nothing else**.

## Help Tags

When stuck after all possible solutions exhausted:
1. `<promise>BLOCKED:brief description</promise>`
2. `<promise>DECIDE:question (Option A vs B)</promise>`

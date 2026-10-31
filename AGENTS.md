# Agent Working Standards

Always apply these standards to all work in this repository.

## Task Execution — One Unit Per Invocation

- **One task per invocation.** Complete exactly one unit of work, commit, and stop. Never batch.
- A "unit" is EITHER one task from `.agent/tasks.json` OR one idea from
  `docs/IMPROVEMENT_PLAN.md` (test one idea → record its ROI row → commit → stop).
- Do not start the next unit without the user's go. Plan first when asked to plan;
  test only when asked to taste.

## Quant Research Rules (apply to every experiment)

1. **No fantasy results.** Every number comes from real historical data with real costs
   (≥10bp/side taker; 3bp maker only with a documented fill model). Assumptions are not results.
2. **Run the bug gate first.** `python scripts/audit_scan.py <script>` and walk the Tier A
   checklist in `.agent/skills/quantitative-trading-bug-hunter/SKILL.md`. Record the audit
   next to the result — an unaudited number must never be claimed.
3. **Placebo or it doesn't count.** Standalone strategies need their own placebo; book changes
   need a blend placebo; best-of-N searches need a selection-adjusted honesty note. Permute
   signals/weights and recompute P&L — never shuffle P&L series.
4. **Unverified claims never enter a book.** If a historical number can't be reproduced from a
   runnable committed definition, demote it to UNVERIFIED (precedent: EXP-044 timeframe claims).
5. **Track everything.** Update the ROI tracker in `docs/IMPROVEMENT_PLAN.md`, the ledger in
   `reports/roi_progress_ledger.json`, and `reports/strategy_leaderboard.json` before committing —
   failures included. Persist results so the best strategy can be selected later.
6. **Adversarial check.** Before reporting, ask what can go wrong and test each failure mode
   (magnitudes vs cost physics, nonzero-position counts, independent re-derivation of top nodes).

## Repo Operations

- **Data files are never tracked in git** (`.gitignore` excludes `data/**.csv`). Restore data
  with `python scripts/restore_data.py`; recovery procedure in `docs/RESTORE_POINT.md`.
- Python env: `python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r requirements.txt`,
  then `pip install "plotly<6.0.0" vectorbt scipy pyarrow nautilus_trader`.
- Work only on the session branch `arena/b657ea09-forex-crypto`; never rename or switch branches.
- Full test suite must pass (`/tmp/venv/bin/python -m pytest tests/ -q`, currently 170) before
  every push.

## Reuse Before Creating

Before writing new code, analyze existing utilities, helpers and tests:

1. **Search first** — grep/glob for similar functionality before implementing
2. **Extend if close** — if something exists that's 80% of what you need, extend it
3. **Extract if duplicating** — if you're about to copy-paste, extract to shared module instead

## File Size & Organization

Keep files between **200-300 lines max**. If a file exceeds this:

1. **Split by responsibility** — one module = one concern
2. **Separate logic from presentation** — helpers in their own modules
3. **Group by feature** — co-locate related files, not by type

## Code Style

1. Prefer writing clear code and use inline comments sparingly
2. Document methods with block comments at the top of the method
3. Use Conventional Commit format

## Test To Verify Functionality

If you didn't test it, it doesn't work.

Verify written code by:
- Running unit tests (`pytest`)
- Checking for runtime errors on a smoke run of the actual script
- For UI work only: Playwright smoke tests and screenshots

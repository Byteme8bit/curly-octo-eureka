# Contributing workflow

The trading bot is maintained by the operator and a Cursor agent working in tandem. This is the loop both follow.

## Per request

1. **Capture the ask.** Create `feature_logs/NNN_short-name.md` with verbatim request and status `in progress`.
2. **Plan briefly.** Skim affected modules (see `docs/architecture/modules.md`). If risky or broad, propose the plan before coding.
3. **Implement** with the patterns in `docs/conventions/patterns.md`.
4. **Test** per `docs/conventions/verification.md`. Add or extend a `tests/` file.
5. **Document.** If you added a module, settings, or a pattern, update:
   - `docs/architecture/modules.md` (new module row)
   - `docs/conventions/patterns.md` (new pattern)
   - `.env.example` (new settings)
   - Feature log **Actions taken** section.
6. **Mark the feature log status `complete`** only after tests run green.

## Branching

For now, work happens directly on the operator's local checkout. Once GitHub backup is unblocked (see `feature_logs/005`), use:

- `main` — known-good, deployable
- Feature branches: `feature/NNN-short-name`
- Merge to `main` only after tests pass

## Commits

- One feature per commit when feasible.
- Message format: `NNN: imperative summary` (e.g. `006: watchdog wall-clock timestamps + error categorization`).
- Body explains *why*, not *what* (the diff shows the what).

## Code review checklist

Before saying "done":

- [ ] Tests added or updated in `tests/`
- [ ] Tests pass locally
- [ ] No `.env` content changes are committed
- [ ] `docs/architecture/modules.md` is current if a module moved/added
- [ ] `.env.example` documents any new settings
- [ ] Naming follows `docs/conventions/naming.md`
- [ ] Feature log status is `complete` and lists the verification used
- [ ] No `print()` for non-display output (use `logger`)
- [ ] No catch-all `except:` (use specific types or `except Exception`)
- [ ] No `time.monotonic()` for values that get persisted to disk

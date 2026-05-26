# Release Checklist

Run this checklist before tagging a new release.

## Repository State

- [ ] `git status --short` is clean.
- [ ] Latest tests pass.
- [ ] Latest frontend build passes.
- [ ] Remote URL is correct.

## Secret Safety

- [ ] `.env` is not tracked.
- [ ] `backend/.env` is not tracked.
- [ ] No API keys are committed.
- [ ] No real database URLs are committed.
- [ ] No private certificates or SSH keys are committed.
- [ ] If any real secret was ever committed, rotate it and rewrite history.

## Package Hygiene

- [ ] No `.venv`.
- [ ] No `node_modules`.
- [ ] No `dist`.
- [ ] No `__pycache__`.
- [ ] No `.pytest_cache` or `.ruff_cache`.
- [ ] No logs or local DB files.
- [ ] No uploaded customer documents.

## Build Clean Archive

```bash
git archive --format=zip --output chatbot-enterprise-source.zip main
```

Then inspect the archive before sending it.

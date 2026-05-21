# Internal Contributing Guide

This is a private commercial source repository. This guide is for internal
contributors, maintainers, contractors, or approved customers with source access.

## Branch Strategy

| Branch prefix | Purpose |
|---|---|
| `feature/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Maintenance, dependency updates |
| `refactor/<name>` | Refactoring without behavior change |

Always branch from `main`. Keep branches short-lived and focused on one concern.

## Development Setup

```bash
# Clone and enter the private repo
git clone <private-repo-url>
cd Chatbot_Enterprise-AI

# Copy environment config
cp .env.example .env    # fill in DATABASE_URL, JWT_SECRET_KEY, ENCRYPTION_KEY

# Start local stack
make dev-hot
```

## Code Style

### Backend (Python 3.12)

- Formatter / linter: **ruff** (config in `backend/pyproject.toml`)
- Run: `make lint` or `cd backend && ruff check .`
- Line length: 100 characters
- Type annotations on all public functions

### Frontend (TypeScript)

- Linter: **ESLint** (`frontend/.eslintrc.cjs`)
- Run: `cd frontend && npm run lint`
- Formatter: Prettier-compatible (no trailing semicolons in TSX)

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add streaming support for Claude provider
fix: correct BM25 score normalization for short queries
docs: update API reference for /chat/stream endpoint
chore: bump sentence-transformers to 3.0
```

## Pull Request Checklist

Before opening a PR, verify:

- [ ] CI passes locally (`make test && make lint`)
- [ ] New functionality has unit tests in `backend/tests/unit/`
- [ ] `.env.example` updated if new env vars were added
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No `.env`, secrets, or large binaries committed
- [ ] No customer documents, customer data, private deployment files, or license-specific files committed
- [ ] Commercial license notices remain intact
- [ ] No raw prompts, user questions, answers, API keys, tokens, or credentials are logged or added to usage metadata
- [ ] Docstrings added for non-obvious functions

## Security and Privacy Rules

- Use `request_id`, token counts, mode, model, source counts, and status flags for debugging instead of raw user content.
- Do not add `question`, `answer`, `answer_preview`, raw web-search query, credential, bearer token, or API key values to logs, telemetry metadata, errors, or admin dashboards.
- If a feature must persist user-visible content, document why it is required, scope access to admins or owners, and add the smallest relevant redaction or retention behavior.

## Running Tests

```bash
# Unit tests only (fast, no external services needed)
make test

# Or directly:
cd backend && pytest tests/unit/ -v

# Integration tests (requires running database)
cd backend && pytest tests/integration/ -v -m integration
```

## Reporting Issues

Use the GitHub issue templates:
- **Bug report** — unexpected behavior, errors, crashes
- **Feature request** — new capabilities or improvements

For security vulnerabilities, see [SECURITY.md](SECURITY.md).

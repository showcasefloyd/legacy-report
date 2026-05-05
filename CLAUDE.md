# CLAUDE.md — Legacy Report

Terminal-based comic book collection tracker. See [README.md](README.md) for setup and [AGENTS.md](AGENTS.md) for full agent rules.

## Stack
- **CLI:** Typer + InquirerPy + Rich
- **DB:** SQLite via SQLAlchemy (ORM), stored at `~/.local/share/legacy-report/collection.db`
- **Python:** 3.11 | **Tests:** pytest

## Key Commands
```bash
source .venv/bin/activate
pip install -e .          # first-time setup
legacy-report             # launch app (interactive menu, cannot be scripted)

.venv/bin/pytest tests/   # run full test suite — required before marking any change done
sqlite3 ~/.local/share/legacy-report/collection.db ".tables"   # inspect DB
gh issue list             # check issues
```

## Testing Rules
Two test layers are **required** for every change:

| Layer | File | Tests |
|-------|------|-------|
| Data | `tests/test_collection.py` | CRUD via `db.py`, in-memory SQLite, no mocks |
| Menu | `tests/test_menu_flows.py` | Mocked InquirerPy flows + `gc.collect()` between steps |

InquirerPy mock pattern:
```python
# Sequential text prompts
m = MagicMock(); m.return_value.execute.side_effect = ["val1", "val2"]
# Single select/confirm
m = MagicMock(); m.return_value.execute.return_value = "choice"
```

Always capture ORM object IDs **before** a menu flow — objects are detached after `session.close()`.

## Conventions
- All DB access through `db.py` — never inline SQL in commands
- Parameterized queries only (`?` placeholders)
- `console.print(...)` over bare `print()`
- `pathlib.Path` for all file paths — no hardcoded strings
- Ask before assuming on anything ambiguous (schema, naming, location)

## What NOT to Do
- Don't skip tests or declare done without a green suite
- Don't write directly to the DB to simulate behavior — use pytest
- Don't install packages without checking `pyproject.toml` first
- Don't use MCPs when `gh`, `sqlite3`, `grep`, etc. will do

## When Compacting

When compacting always preserve the full list of modified files and current test status

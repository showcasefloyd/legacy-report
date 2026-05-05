# AGENTS.md — Legacy Report

This file defines how AI agents (GitHub Copilot, Claude Sonnet) should behave when working on this project. Read it fully before making any changes.

---

## Project Overview

**Legacy Report** is a terminal-based comic book tracking application built in Python 3.11. Users interact via a rich CLI interface to track their comic collection, reading progress, wishlists, and series metadata.

**Stack:**

- **UI:** [Typer](https://typer.tiangolo.com/) (CLI commands) + [InquirerPy](https://inquirerpy.readthedocs.io/) (interactive prompts) + [Rich](https://rich.readthedocs.io/) (terminal formatting)
- **Database:** SQLite via Python's built-in `sqlite3` module (or SQLAlchemy if present)
- **Language:** Python 3.11
- **Tests:** pytest

---

## Agent Behavior Rules

### 1. Prefer CLI Tools Over MCPs for System Interaction

When you need to interact with the system — querying the database, working with Git, inspecting files — **reach for the appropriate CLI tool first.** Only use an MCP if no CLI tool can accomplish the task.

**Common system tasks and their preferred CLI tools:**

| Task                                    | Use this                    |
| --------------------------------------- | --------------------------- |
| Git operations (commits, PRs, issues)   | `gh` (GitHub CLI)           |
| Database inspection / queries           | `sqlite3`                   |
| File search and inspection              | `grep`, `find`, `cat`, `ls` |
| JSON processing                         | `jq`                        |
| Running tests                           | `pytest`                    |
| Package management                      | `pip`                       |
| Launching the app (manual testing only) | `legacy_report`             |

**Examples:**

```bash
# Check open GitHub issues
gh issue list

# Create a PR
gh pr create --title "Add reading progress tracking"

# Query the database directly
sqlite3 collection.db "SELECT * FROM comics LIMIT 10;"

# Inspect a JSON file
cat data/export.json | jq '.comics[]'
```

MCP tools are a last resort — if a shell command covers it, use that.

---

### 2. Running the Application

After installing dependencies, launch the app with:

```bash
pip install -e .   # first time only
legacy_report      # launches the interactive menu
```

**Legacy Report is menu-driven, not command-driven.** Running `legacy_report` drops the user into an interactive InquirerPy menu session:

```
? Main Menu
  1) Search My Collection
  2) Add Issue
  3) Edit Issue
  4) Delete Issue
  5) Setup / Configuration
  6) Quit
```

There are no subcommands to pass at the prompt. Agents **cannot automate navigation through the menus** — do not attempt to pipe input or script keypresses to test app behavior. Instead, verify behavior by:

- Writing and running **pytest tests** that call the underlying functions directly
- Using **`sqlite3`** to inspect the database before and after a manual test run
- Reading the relevant module code to confirm logic is correct

---

### 3. Database Interactions

The app uses a local **SQLite** database file (likely `collection.db` or similar in the project root or `data/`).

**For raw inspection and debugging, use `sqlite3` directly:**

```bash
sqlite3 collection.db ".tables"
sqlite3 collection.db ".schema comics"
sqlite3 collection.db "SELECT * FROM comics ORDER BY id DESC LIMIT 10;"
```

**Never write directly to the database** (via raw SQL `INSERT`/`UPDATE`) to simulate app behavior.
Always go through `legacy_report` commands so validation and business logic are exercised.

For schema resets or seeding during development:

```bash
bash scripts/reset_db.sh     # if it exists
python scripts/seed.py       # if it exists
```

If these scripts don't exist yet and you need them, create them in `scripts/` and document them here.

---

### 4. Running Tests

This project uses **pytest**.

```bash
# Run all tests
.venv/bin/pytest tests/

# Run a specific test file
.venv/bin/pytest tests/test_collection.py

# Run with output (useful for debugging)
.venv/bin/pytest tests/ -s

# Run with coverage (if pytest-cov is installed)
.venv/bin/pytest --cov=. --cov-report=term-missing
```

**Tests are not optional.** Every code change must be accompanied by tests that verify the change works. This is non-negotiable — do not declare a change "done" until:

1. You have written tests covering the new or modified behavior
2. You have run the full test suite and it passes
3. You have confirmed the previously-passing tests still pass

**Two test layers are required for this project:**

| Layer | File | What to test |
|-------|------|--------------|
| Data layer | `tests/test_collection.py` | CRUD functions in `db.py` — use an in-memory SQLite session, no mocks |
| Menu layer | `tests/test_menu_flows.py` | Full menu flows with mocked InquirerPy prompts + `gc.collect()` between select and mutate steps |

The menu layer tests exist specifically to catch `ObjectDereferencedError` and session lifecycle bugs that the data layer tests cannot see — InquirerPy runs an asyncio event loop between prompts, which gives CPython's GC a chance to collect SQLAlchemy weak references. Always include a GC pressure test when adding a new menu flow that mutates data.

**Mock pattern for InquirerPy in tests:**

```python
# Multiple sequential text prompts — put values on execute.side_effect
def _text_mock(*values):
    m = MagicMock()
    m.return_value.execute.side_effect = list(values)
    return m

# Single select / confirm prompt
def _single_mock(return_value):
    m = MagicMock()
    m.return_value.execute.return_value = return_value
    return m
```

Always store ORM object IDs before a menu flow runs — `session.close()` at the end of a flow detaches all objects, and accessing attributes on a detached object raises `DetachedInstanceError`.

If tests fail before your change, note it explicitly — don't mask pre-existing failures.

---

### 5. Verifying Changes

Because Legacy Report is menu-driven, agents cannot automate end-to-end flows through the UI. Use this approach instead:

**For logic and data changes — write tests first, then run them:**

```bash
.venv/bin/pytest tests/                          # full suite
.venv/bin/pytest tests/test_collection.py -s    # specific module, with output
.venv/bin/pytest tests/test_menu_flows.py -s    # menu-level flows
```

A change is not verified until the test suite is green. Syntax checking (`python -m py_compile`) and reading code are not substitutes for running tests.

**For database changes — use sqlite3 to inspect state:**

```bash
sqlite3 collection.db ".schema"
sqlite3 collection.db "SELECT * FROM issue ORDER BY id DESC LIMIT 5;"
```

**For UI / prompt changes** — manually run `legacy_report` and navigate to the affected menu. Note what you observed in your PR or commit message.

Always run the full test suite before and after changes. If tests were already failing before your change, note it explicitly — don't mask pre-existing failures.

For UI changes (Rich output, InquirerPy prompts), manually invoke the command and observe terminal output. Screenshot or paste the output in your PR description if relevant.

---

### 6. Code Style and Conventions

- Follow **PEP 8**. Use a formatter if one is configured (check for `pyproject.toml`, `.flake8`, or `ruff.toml`).
- Type hints are encouraged, especially on Typer command signatures.
- Rich output (tables, panels, colors) should degrade gracefully — avoid crashing if terminal doesn't support color.
- InquirerPy prompts should always have a clear cancel/back path where possible.
- Keep Typer commands focused — one responsibility per command.
- SQLite access should go through a single data layer (e.g. `db.py` or a `database/` module), not scattered inline across commands.

---

### 7. File Structure Reference

```
.
├── main.py               # Typer app entrypoint
├── collection.db             # SQLite database (gitignored)
├── scripts/              # Dev utility scripts (seed, reset, migrate)
├── tests/                # pytest test files
├── AGENTS.md             # This file
└── ...                   # Other modules (db, models, ui, etc.)
```

Update this tree if the structure changes significantly.

---

### 8. What Agents Should NOT Do

- **Don't install packages** without checking `requirements.txt` or `pyproject.toml` first — ask or note the addition explicitly.
- **Don't hardcode file paths** — use `pathlib.Path` and derive paths relative to the project root.
- **Don't write directly to `collection.db`** to simulate app behavior — use pytest to test the underlying functions, and `sqlite3` to inspect state.
- **Don't skip tests** to make a change "simpler." Write the test.
- **Don't declare a change done** without running the full test suite and confirming it passes.
- **Don't rely on syntax checks or code reading** as a substitute for running tests — tests catch runtime bugs that static analysis cannot.
- **Don't use an MCP** when a CLI tool (`gh`, `sqlite3`, `grep`, etc.) can do the job.

---

## Notes for GitHub Copilot

- Copilot should respect the Typer command structure — don't suggest `argparse` or `click` patterns.
- When autocompleting database queries, prefer parameterized queries (`?` placeholders) to avoid injection patterns.
- Rich console output (`console.print(...)`) is preferred over bare `print()`.

## Notes for Claude Sonnet

- When planning new features or large changes, grill me until you have a clear understanding of what we are building
- Before proposing a solution, check whether an existing CLI command already covers the use case.
- When asked to debug, start by running the relevant command and reading the actual output.
- Prefer editing existing modules over creating new files unless structure clearly calls for it.
- If something is ambiguous (schema, command name, file location), ask before assuming.

---

_Last updated: May 2026. Update this file as the project evolves._

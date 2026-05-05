# Backlog

**Rule: Delete items when shipped. Git history is the archive. This file is live work only.**

---

## v1 MVP — Completed ✓

- [x] Fix search display — remove redundant `print_issues_table()` call in `search_collection()`
- [x] Browse mode — list all Series with issue counts
- [x] Pagination — `[prev] / [next]` for large result sets
- [x] Stats in header — "X issues across Y series"
- [x] Sort options — by Issue #, LGY #, or Pub Date
- [x] Consistent cancel paths
- [x] Post-action confirmation — `print_issue_detail()` after Add/Edit
- [x] Read/Unread status — `read: bool` on Issue, filterable, badged in table
- [x] Personal rating — `rating: Optional[int]` (1–5), rendered as stars
- [x] Export to CSV
- [x] Textual TUI foundation — full-screen two-pane app replaces InquirerPy main menu

---

## v2 — Textual TUI Migration

> **Direction:** All features must be migrated to native Textual screens.
> `suspend()` into InquirerPy is unreliable — each action must become a proper Textual screen or modal.

### Phase 1 — Quick wins (can be done in parallel)

- [ ] **Live search / filter** — press `/` to open an `Input` widget that live-filters the DataTable (Series title, Story title, Issue #, LGY #). Esc clears it. No suspend, no API calls.
- [ ] **Delete confirmation modal** — `DeleteConfirmScreen(ModalScreen)`: shows issue label, `[D]elete` / `[Esc]cancel`. Calls `db.delete_issue()` directly on confirm, then reloads data.
- [ ] **Export CSV in-TUI** — run export logic in a Textual worker thread, show `notify()` toast on success/fail. No terminal hand-off.

### Phase 2 — Edit Issue Modal

- [ ] **`EditIssueScreen(ModalScreen)`** — `Input` widgets pre-filled with selected issue's fields (issue #, LGY #, pub date, story title, writer, artist, rating). Submit calls `db.update_issue()`, dismiss reloads data.

### Phase 3 — Config Screen

- [ ] **`ConfigScreen(Screen)`** — pushed via `c` key. Shows masked API key, DB path, cache TTL. API key input + "Validate & Save" button (validates via `comicvine.validate_api_key()` in a worker thread).

### Phase 4 — Add Issue Wizard *(depends on Phase 2 for field pattern)*

- [ ] **`AddIssueScreen` multi-step wizard** — all in Textual, no suspend:
  - Step 1: `Input` → `comicvine.search_volumes()` in worker → results DataTable with loading spinner
  - Step 2: Select volume → `comicvine.get_issues_for_volume()` in worker → issues DataTable
  - Step 3: Select issue → pre-fill Edit-style fields (auto-calculated LGY shown)
  - Step 4: Confirm/edit → `db.create_issue()` → dismiss + reload main view

### Phase 5 — Docs

- [ ] **`PRD-v2.md`** — new PRD: Textual as primary TUI, updated tech stack, application flow (screens not menus), updated project structure diagram
- [ ] **`CLAUDE.md`** — add Textual to stack, note InquirerPy retained for `menu.py` test coverage, update key commands
- [ ] **`AGENTS.md`** — update tech stack table and file structure reference diagram
- [ ] **`README.md`** — update intro and dependencies section
- [ ] **`tui.py` cleanup** — remove remaining `suspend()` stubs + dead `menu.py` imports once all phases ship

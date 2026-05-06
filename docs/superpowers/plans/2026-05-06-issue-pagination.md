# Issue Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add page-by-page pagination to the Add Issue wizard's issue selection step so titles with more than 100 ComicVine issues are fully accessible.

**Architecture:** `get_issues_for_volume` gains `offset`/`limit` params and returns a structured dict including `total`. `AddIssueScreen` tracks current offset and total, renders a page label and Prev/Next buttons below the issues table, and exposes `[`/`]` keybindings that trigger re-fetches. Each page is cached independently via the existing cache layer — no cache layer changes needed.

**Tech Stack:** Python 3.11+, Textual TUI, SQLite/SQLModel, ComicVine API via httpx, pytest + pytest-asyncio (strict mode)

---

## File Map

| File | Change |
|------|--------|
| `legacy_report/config.py` | Reduce `cache_ttl_hours` default from 24 → 12 |
| `legacy_report/comicvine.py` | `get_issues_for_volume`: add `offset`/`limit` params, return dict instead of list |
| `legacy_report/tui.py` | `AddIssueScreen`: new `_cv_offset`/`_cv_total` state; page nav widgets; `[`/`]` bindings; update `_fetch_issues`, `_show_step`, `_show_loading`, `on_button_pressed`, `_STEP_HELP` |
| `tests/test_comicvine.py` | New file: unit tests for `get_issues_for_volume` return shape and offset forwarding |
| `tests/test_tui.py` | Update 2 existing mocks; add 4 new pagination tests |

---

### Task 1: Reduce default cache TTL to 12 hours

**Files:**
- Modify: `legacy_report/config.py:8`

- [ ] **Step 1: Change the default**

In `legacy_report/config.py`, change:

```python
DEFAULT_CONFIG = {
    "comicvine_api_key": "",
    "cache_ttl_hours": 24,
    "db_path": "~/.local/share/legacy-report/collection.db",
}
```

to:

```python
DEFAULT_CONFIG = {
    "comicvine_api_key": "",
    "cache_ttl_hours": 12,
    "db_path": "~/.local/share/legacy-report/collection.db",
}
```

- [ ] **Step 2: Run full test suite to confirm no breakage**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests pass. The one test that patches `get_config` with `"cache_ttl_hours": 24` is self-contained and unaffected.

- [ ] **Step 3: Commit**

```bash
git add legacy_report/config.py
git commit -m "config: reduce default cache_ttl_hours from 24 to 12"
```

---

### Task 2: Update `get_issues_for_volume` to accept offset and return a structured dict

**Files:**
- Create: `tests/test_comicvine.py`
- Modify: `legacy_report/comicvine.py:90-101`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_comicvine.py`:

```python
from unittest.mock import patch
from legacy_report import comicvine


def test_get_issues_for_volume_returns_structured_dict():
    fake_response = {
        "results": [
            {"id": 1, "issue_number": "1", "name": "First Issue",
             "cover_date": "1963-03-01", "person_credits": [], "image": {}}
        ],
        "number_of_total_results": 342,
        "offset": 0,
        "limit": 100,
    }
    with patch("legacy_report.comicvine._fetch", return_value=fake_response):
        result = comicvine.get_issues_for_volume("123")

    assert result["total"] == 342
    assert result["offset"] == 0
    assert result["limit"] == 100
    assert len(result["results"]) == 1
    assert result["results"][0]["issue_number"] == "1"


def test_get_issues_for_volume_passes_offset_to_fetch():
    fake_response = {
        "results": [],
        "number_of_total_results": 342,
        "offset": 100,
        "limit": 100,
    }
    with patch("legacy_report.comicvine._fetch", return_value=fake_response) as mock_fetch:
        comicvine.get_issues_for_volume("123", offset=100)

    _, call_params = mock_fetch.call_args[0]
    assert call_params["offset"] == 100
    assert call_params["limit"] == 100
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_comicvine.py -v
```

Expected: both tests FAIL — `get_issues_for_volume` currently returns a list, not a dict with `total`/`offset`/`limit` keys.

- [ ] **Step 3: Implement the updated `get_issues_for_volume`**

Replace lines 90–101 in `legacy_report/comicvine.py`:

```python
def get_issues_for_volume(volume_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Get one page of issues for a given ComicVine volume ID."""
    data = _fetch(
        "issues",
        {
            "filter": f"volume:{volume_id}",
            "field_list": "id,name,issue_number,cover_date,description,person_credits,image",
            "sort": "cover_date:asc",
            "limit": limit,
            "offset": offset,
        },
    )
    return {
        "results": data.get("results", []),
        "total": data.get("number_of_total_results", 0),
        "offset": offset,
        "limit": limit,
    }
```

- [ ] **Step 4: Run comicvine tests to verify they pass**

```bash
.venv/bin/pytest tests/test_comicvine.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_comicvine.py legacy_report/comicvine.py
git commit -m "feat: paginate get_issues_for_volume — offset/limit params, structured dict return"
```

---

### Task 3: Update `_fetch_issues` in `AddIssueScreen` to consume the new API contract

**Files:**
- Modify: `legacy_report/tui.py` (`AddIssueScreen.__init__`, `on_data_table_row_selected`, `_fetch_issues`)
- Modify: `tests/test_tui.py` (update 2 existing mocks; add 1 new test)

- [ ] **Step 1: Update the two existing mocks that return a bare list**

In `tests/test_tui.py`, `test_fetch_issues_worker_advances_to_step3` patches `get_issues_for_volume` with a bare list. After this task, `_fetch_issues` will expect a dict — update it now so the existing test stays green.

Find this block (around line 597):

```python
with patch(
    "legacy_report.comicvine.get_issues_for_volume",
    return_value=_FAKE_CV_ISSUES,
):
```

Change to:

```python
with patch(
    "legacy_report.comicvine.get_issues_for_volume",
    return_value={"results": _FAKE_CV_ISSUES, "total": 5, "offset": 0, "limit": 100},
):
```

Find the same pattern in `test_wizard_row_select_does_not_open_detail_modal` (around line 649):

```python
with patch(
    "legacy_report.comicvine.get_issues_for_volume",
    return_value=_FAKE_CV_ISSUES,
):
```

Change to:

```python
with patch(
    "legacy_report.comicvine.get_issues_for_volume",
    return_value={"results": _FAKE_CV_ISSUES, "total": 1, "offset": 0, "limit": 100},
):
```

- [ ] **Step 2: Write the new failing test**

Add to `tests/test_tui.py`:

```python
@pytest.mark.asyncio
async def test_fetch_issues_stores_total_and_offset(mem_engine):
    """_fetch_issues stores _cv_total and _cv_offset from the API page dict."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES
    fake_page = {"results": _FAKE_CV_ISSUES, "total": 342, "offset": 0, "limit": 100}

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=fake_page,
            ):
                screen.run_worker(screen._fetch_issues("42", offset=0), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            assert screen._step == _WIZARD_STEP_ISSUES
            assert screen._cv_total == 342
            assert screen._cv_offset == 0
```

- [ ] **Step 3: Run tests to confirm the new test fails**

```bash
.venv/bin/pytest tests/test_tui.py::test_fetch_issues_stores_total_and_offset -v
```

Expected: FAIL — `AddIssueScreen` has no `_cv_total` or `_cv_offset` attributes yet.

- [ ] **Step 4: Add `_cv_offset` and `_cv_total` to `AddIssueScreen.__init__`**

In `legacy_report/tui.py`, update `AddIssueScreen.__init__`:

```python
def __init__(self) -> None:
    super().__init__()
    self._step: str = _WIZARD_STEP_SEARCH
    self._volumes: list[dict] = []
    self._cv_issues: list[dict] = []
    self._cv_offset: int = 0
    self._cv_total: int = 0
    self._selected_volume: Optional[dict] = None
    self._selected_cv_issue: Optional[dict] = None
```

- [ ] **Step 5: Reset `_cv_offset` on volume select**

In `legacy_report/tui.py`, update the `_WIZARD_STEP_VOLUMES` branch of `on_data_table_row_selected`:

```python
if self._step == _WIZARD_STEP_VOLUMES:
    idx = event.cursor_row
    if 0 <= idx < len(self._volumes):
        self._selected_volume = self._volumes[idx]
        self._cv_offset = 0
        self._show_loading()
        self.run_worker(
            self._fetch_issues(str(self._selected_volume["id"]), offset=0),
            exclusive=True,
        )
```

- [ ] **Step 6: Update `_fetch_issues` to unpack the page dict**

Replace the entire `_fetch_issues` method in `legacy_report/tui.py`:

```python
async def _fetch_issues(self, volume_id: str, offset: int = 0) -> None:
    from legacy_report import comicvine
    try:
        page = await asyncio.to_thread(
            comicvine.get_issues_for_volume, volume_id, offset
        )
    except Exception as e:
        self.notify(str(e), title="Fetch Failed", severity="error")
        self._show_step(_WIZARD_STEP_VOLUMES)
        return

    issues = page["results"]
    if not issues and offset == 0:
        self.notify("No issues found for this series.", severity="warning")
        self._show_step(_WIZARD_STEP_VOLUMES)
        return

    self._cv_issues = issues
    self._cv_offset = offset
    self._cv_total = page["total"]

    table = self.query_one("#wiz-issues-table", DataTable)
    table.clear(columns=True)
    table.add_columns("Issue #", "Story Title", "Cover Date")
    for iss in issues:
        table.add_row(
            iss.get("issue_number", "—"),
            iss.get("name") or "—",
            iss.get("cover_date", "—"),
        )
    self._show_step(_WIZARD_STEP_ISSUES)
    table.focus()
```

- [ ] **Step 7: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add legacy_report/tui.py tests/test_tui.py
git commit -m "feat: update _fetch_issues to consume paginated API dict, track offset/total"
```

---

### Task 4: Add pagination UI — page label, Prev/Next buttons, `[`/`]` keybindings

**Files:**
- Modify: `legacy_report/tui.py` (CSS, `compose`, `_show_step`, `_show_loading`, `_fetch_issues`, `on_button_pressed`, `BINDINGS`, `_STEP_HELP`; add `action_prev_page`, `action_next_page`)
- Modify: `tests/test_tui.py` (add 3 new tests)

- [ ] **Step 1: Write the three failing tests**

Add to `tests/test_tui.py`:

```python
@pytest.mark.asyncio
async def test_next_page_fetches_offset_100(mem_engine):
    """] key on the issues step fetches the next page at offset=100."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES

    page1 = {"results": _FAKE_CV_ISSUES, "total": 150, "offset": 0, "limit": 100}
    page2 = {"results": _FAKE_CV_ISSUES, "total": 150, "offset": 100, "limit": 100}

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=page1,
            ):
                screen.run_worker(screen._fetch_issues("42", offset=0), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            assert screen._step == _WIZARD_STEP_ISSUES
            assert screen._cv_offset == 0

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=page2,
            ):
                await pilot.press("]")
                for _ in range(5):
                    await pilot.pause()

            assert screen._cv_offset == 100


@pytest.mark.asyncio
async def test_next_page_noop_on_last_page(mem_engine):
    """] key on the last page does not trigger another fetch."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES

    # total=50 means one page; offset+100 >= 50 so next is disabled
    page1 = {"results": _FAKE_CV_ISSUES, "total": 50, "offset": 0, "limit": 100}

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=page1,
            ):
                screen.run_worker(screen._fetch_issues("42", offset=0), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            assert screen._step == _WIZARD_STEP_ISSUES

            with patch(
                "legacy_report.comicvine.get_issues_for_volume"
            ) as mock_fetch:
                await pilot.press("]")
                for _ in range(5):
                    await pilot.pause()
                mock_fetch.assert_not_called()

            assert screen._cv_offset == 0


@pytest.mark.asyncio
async def test_prev_page_noop_on_first_page(mem_engine):
    """[ key on page 1 does not trigger another fetch."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES

    page1 = {"results": _FAKE_CV_ISSUES, "total": 342, "offset": 0, "limit": 100}

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=page1,
            ):
                screen.run_worker(screen._fetch_issues("42", offset=0), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            with patch(
                "legacy_report.comicvine.get_issues_for_volume"
            ) as mock_fetch:
                await pilot.press("[")
                for _ in range(5):
                    await pilot.pause()
                mock_fetch.assert_not_called()

            assert screen._cv_offset == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_tui.py::test_next_page_fetches_offset_100 tests/test_tui.py::test_next_page_noop_on_last_page tests/test_tui.py::test_prev_page_noop_on_first_page -v
```

Expected: all three FAIL — `[` and `]` bindings don't exist, offset doesn't advance.

- [ ] **Step 3: Add CSS for the page navigation container**

In `legacy_report/tui.py`, add to `AddIssueScreen.DEFAULT_CSS` (after the `#lgy-hint` rule block):

```css
    AddIssueScreen #wiz-page-nav {
        height: 3;
        align: center middle;
    }
    AddIssueScreen #wiz-page-label {
        width: 1fr;
        content-align: center middle;
        color: #00aa22;
    }
```

- [ ] **Step 4: Add page nav widgets to `compose()`**

In `legacy_report/tui.py`, in `AddIssueScreen.compose`, add the `#wiz-page-nav` container directly after the `#wiz-issues-table` yield:

```python
yield DataTable(id="wiz-issues-table", cursor_type="row", zebra_stripes=True)
with Horizontal(id="wiz-page-nav"):
    yield Button("← Prev", id="btn-prev-page")
    yield Static("", id="wiz-page-label")
    yield Button("Next →", id="btn-next-page")
yield LoadingIndicator(id="wiz-loading")
```

- [ ] **Step 5: Toggle `#wiz-page-nav` in `_show_step`**

In `legacy_report/tui.py`, in `AddIssueScreen._show_step`, add one line after the `#wiz-issues-table` line:

```python
self.query_one("#wiz-search-input",  Input).display     = (step == _WIZARD_STEP_SEARCH)
self.query_one("#wiz-volumes-table", DataTable).display = (step == _WIZARD_STEP_VOLUMES)
self.query_one("#wiz-issues-table",  DataTable).display = (step == _WIZARD_STEP_ISSUES)
self.query_one("#wiz-page-nav").display                 = (step == _WIZARD_STEP_ISSUES)
self.query_one("#wiz-loading",       LoadingIndicator).display = False
```

- [ ] **Step 6: Hide `#wiz-page-nav` during loading**

In `legacy_report/tui.py`, update `AddIssueScreen._show_loading`:

```python
def _show_loading(self) -> None:
    for wid in ("wiz-search-input", "wiz-volumes-table", "wiz-issues-table", "wiz-page-nav"):
        self.query_one(f"#{wid}").display = False
    self.query_one("#wiz-loading", LoadingIndicator).display = True
```

- [ ] **Step 7: Update `_fetch_issues` to update the page label and button states**

In `legacy_report/tui.py`, add these lines to `_fetch_issues` after `self._cv_total = page["total"]` and before the table rebuild:

```python
limit = page["limit"]
total_pages = (self._cv_total + limit - 1) // limit if self._cv_total else 1
current_page = (offset // limit) + 1
self.query_one("#wiz-page-label", Static).update(
    f"Page {current_page} of {total_pages} ({self._cv_total} issues)"
)
self.query_one("#btn-prev-page", Button).disabled = (offset == 0)
self.query_one("#btn-next-page", Button).disabled = (offset + limit >= self._cv_total)
```

The full `_fetch_issues` at this point:

```python
async def _fetch_issues(self, volume_id: str, offset: int = 0) -> None:
    from legacy_report import comicvine
    try:
        page = await asyncio.to_thread(
            comicvine.get_issues_for_volume, volume_id, offset
        )
    except Exception as e:
        self.notify(str(e), title="Fetch Failed", severity="error")
        self._show_step(_WIZARD_STEP_VOLUMES)
        return

    issues = page["results"]
    if not issues and offset == 0:
        self.notify("No issues found for this series.", severity="warning")
        self._show_step(_WIZARD_STEP_VOLUMES)
        return

    self._cv_issues = issues
    self._cv_offset = offset
    self._cv_total = page["total"]

    limit = page["limit"]
    total_pages = (self._cv_total + limit - 1) // limit if self._cv_total else 1
    current_page = (offset // limit) + 1
    self.query_one("#wiz-page-label", Static).update(
        f"Page {current_page} of {total_pages} ({self._cv_total} issues)"
    )
    self.query_one("#btn-prev-page", Button).disabled = (offset == 0)
    self.query_one("#btn-next-page", Button).disabled = (offset + limit >= self._cv_total)

    table = self.query_one("#wiz-issues-table", DataTable)
    table.clear(columns=True)
    table.add_columns("Issue #", "Story Title", "Cover Date")
    for iss in issues:
        table.add_row(
            iss.get("issue_number", "—"),
            iss.get("name") or "—",
            iss.get("cover_date", "—"),
        )
    self._show_step(_WIZARD_STEP_ISSUES)
    table.focus()
```

- [ ] **Step 8: Add `[` and `]` to `BINDINGS`**

In `legacy_report/tui.py`, update `AddIssueScreen.BINDINGS`:

```python
BINDINGS = [
    Binding("escape", "go_back_or_cancel", "Back / Cancel"),
    Binding("ctrl+s", "save_issue", "Save", show=False),
    Binding("[", "prev_page", "Prev Page", show=False),
    Binding("]", "next_page", "Next Page", show=False),
]
```

- [ ] **Step 9: Add `action_prev_page` and `action_next_page`**

Add both methods to `AddIssueScreen` in `legacy_report/tui.py` (after `action_go_back_or_cancel`):

```python
def action_prev_page(self) -> None:
    if self._step != _WIZARD_STEP_ISSUES or self._cv_offset == 0:
        return
    new_offset = self._cv_offset - 100
    self._show_loading()
    self.run_worker(
        self._fetch_issues(str(self._selected_volume["id"]), offset=new_offset),
        exclusive=True,
    )

def action_next_page(self) -> None:
    if self._step != _WIZARD_STEP_ISSUES or self._cv_offset + 100 >= self._cv_total:
        return
    new_offset = self._cv_offset + 100
    self._show_loading()
    self.run_worker(
        self._fetch_issues(str(self._selected_volume["id"]), offset=new_offset),
        exclusive=True,
    )
```

- [ ] **Step 10: Add Prev/Next button handlers**

In `legacy_report/tui.py`, update `AddIssueScreen.on_button_pressed`:

```python
def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == "btn-wiz-save":
        self.action_save_issue()
    elif event.button.id == "btn-wiz-cancel":
        self.app.pop_screen()
    elif event.button.id == "btn-prev-page":
        self.action_prev_page()
    elif event.button.id == "btn-next-page":
        self.action_next_page()
```

- [ ] **Step 11: Update the issues step help text**

In `legacy_report/tui.py`, update `_STEP_HELP`:

```python
_STEP_HELP = {
    _WIZARD_STEP_SEARCH:  "  Type a title and press Enter ↵  ·  Esc exits",
    _WIZARD_STEP_VOLUMES: "  ↑ ↓ navigate  ·  Enter ↵ to select a series  ·  Esc to go back",
    _WIZARD_STEP_ISSUES:  "  ↑ ↓ navigate  ·  Enter ↵ to select an issue  ·  [ ] page  ·  Esc to go back",
    _WIZARD_STEP_CONFIRM: "  Edit any field  ·  Ctrl+S to save  ·  Esc to go back",
}
```

- [ ] **Step 12: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add legacy_report/tui.py tests/test_tui.py
git commit -m "feat: add Prev/Next pagination UI and [ ] keybindings to Add Issue wizard"
```

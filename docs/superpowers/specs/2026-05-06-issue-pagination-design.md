# Issue Pagination Design

**Date:** 2026-05-06
**Status:** Approved
**Closes:** GitHub issue #9 — Pagination for titles with more than 100 issues

---

## Problem

`comicvine.get_issues_for_volume` hardcodes `limit: 100`, which is the ComicVine API maximum per request. Series with more than 100 issues (e.g. Amazing Spider-Man, X-Men) are silently truncated in the Add Issue wizard. Users cannot reach issues beyond the first 100.

---

## Approach

API-level pagination with per-page caching. The wizard navigates one page (100 issues) at a time via explicit Prev/Next controls. Each page is cached independently using the existing cache layer, so revisiting a page is instant and free against the ComicVine rate limit.

---

## API Layer (`comicvine.py`)

`get_issues_for_volume` gains two new parameters:

```python
def get_issues_for_volume(volume_id: str, offset: int = 0, limit: int = 100) -> dict:
```

Both `offset` and `limit` are included in the `params` dict passed to `_fetch`. Because `_cache_key` hashes all params, each `(volume_id, offset)` pair gets its own cache entry automatically — no changes to the cache layer.

Return type changes from `list` to `dict`:

```python
{
    "results": [...],    # up to 100 issues
    "total": 342,        # number_of_total_results from the ComicVine response
    "offset": 0,         # echoed back for the caller
    "limit": 100,
}
```

`number_of_total_results` is present in every ComicVine response and is already fetched — we just surface it.

---

## Wizard UI (`tui.py` — `AddIssueScreen`)

### New state

```python
_cv_offset: int = 0   # current page offset
_cv_total: int = 0    # total issue count from API
```

`_cv_offset` resets to 0 whenever a new volume is selected.

### New widgets (issues step only)

- **Page label** — `Static`, centered below the table: `"Page 2 of 7 (342 issues)"`
- **Prev button** — `"← Prev"`, disabled on page 1
- **Next button** — `"Next →"`, disabled on the last page

### Keybindings

| Key | Action |
|-----|--------|
| `[` | Previous page (no-op if on page 1) |
| `]` | Next page (no-op if on last page) |

The `#wiz-help` hint for `_WIZARD_STEP_ISSUES` is updated to:

```
↑ ↓ navigate  ·  Enter ↵ to select an issue  ·  [ ] page  ·  Esc to go back
```

### Page turn behaviour

Page turns call `_fetch_issues(volume_id, offset)` in a worker thread. The existing loading spinner covers the table during the fetch. On completion, the table is rebuilt and the page label and button states are updated. On fetch failure, `notify()` shows the error, the wizard stays on the current step, and the offset is not advanced.

---

## Cache & Performance

No changes to the cache layer. Each `(volume_id, offset)` combination maps to a unique cache key because `offset` is part of `params`. Revisiting a page (e.g. going forward then back) hits the cache and is instant.

The global `cache_ttl_hours` default is reduced from 24h to **12h** in `config.py`. This is a pragmatic middle ground: back-catalog data is stable enough that 12h is still very conservative, while ongoing series see a new issue at most monthly — 12h keeps the wizard reasonably fresh without hammering the ComicVine rate limit.

A per-volume cache invalidation ("Refresh") button is tracked separately in GitHub issue #10.

---

## Error Handling

Follows the existing pattern: any exception in the worker is caught, shown via `notify(..., severity="error")`, and the wizard stays on its current step. The user can retry the page turn.

---

## Testing (`test_tui.py`)

Three new headless Textual test cases:

1. **First page loads** — mock `get_issues_for_volume(offset=0)` returning a page dict with `total=342`; assert issues table is visible and page label reads `"Page 1 of 4"`.
2. **Next page** — press `]`; assert `get_issues_for_volume` is called with `offset=100`; assert page label updates to `"Page 2 of 4"` and Prev button is enabled.
3. **Last page boundary** — mock a last-page response; assert Next button is disabled and pressing `]` is a no-op (no additional fetch call).

No new `test_collection.py` tests — this feature has no DB CRUD changes.

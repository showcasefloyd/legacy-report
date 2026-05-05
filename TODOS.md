# Backlog

**Rule: Delete items when shipped. Git history is the archive. This file is live work only.**

---

## Tier 1 — Already planned, minimal effort

- [x] Fix search display — remove redundant `print_issues_table()` call in `search_collection()`; the InquirerPy select list already shows the same data
- [x] Browse mode — new menu item: list all Series with issue counts (one query, one Rich table)
- [x] Pagination — add page offset to DB queries + `[prev] / [next]` choices in selectors; target threshold: >100 results

## Tier 2 — Small wins, no schema changes

- [x] Stats in header — show "X issues across Y series" in `print_header()` (two COUNT queries)
- [x] Sort options — after search, offer sort by Issue #, LGY #, or Pub Date (in-memory re-sort)
- [x] Consistent cancel paths — search flow now has sort prompt with explicit Cancel choice
- [x] Post-action confirmation — after Add/Edit, call `print_issue_detail()` instead of just a success toast

## Tier 3 — Schema additions, medium effort

- [x] Read/Unread status — add `read: bool = False` to `Issue`; filterable, badged in table
- [x] Personal rating — add `rating: Optional[int]` (1–5) to `Issue`; render as stars in detail view
- [x] Export to CSV — walk all issues, write via `csv.writer`; no new dependencies

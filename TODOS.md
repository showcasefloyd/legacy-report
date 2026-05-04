# Backlog

**Rule: Delete items when shipped. Git history is the archive. This file is live work only.**

---

## Tier 1 — Already planned, minimal effort

- [ ] Fix search display — remove redundant `print_issues_table()` call in `search_collection()`; the InquirerPy select list already shows the same data
- [ ] Browse mode — new menu item: list all Series with issue counts (one query, one Rich table)
- [ ] Pagination — add page offset to DB queries + `[prev] / [next]` choices in selectors; target threshold: >100 results

## Tier 2 — Small wins, no schema changes

- [ ] Stats in header — show "X issues across Y series" in `print_header()` (two COUNT queries)
- [ ] Sort options — after search, offer sort by Issue #, LGY #, or Pub Date (in-memory re-sort)
- [ ] Consistent cancel paths — search flow lacks a back/cancel; add it to match edit/delete
- [ ] Post-action confirmation — after Add/Edit, call `print_issue_detail()` instead of just a success toast

## Tier 3 — Schema additions, medium effort

- [ ] Read/Unread status — add `read: bool = False` to `Issue`; filterable, badged in table
- [ ] Personal rating — add `rating: Optional[int]` (1–5) to `Issue`; render as stars in detail view
- [ ] Export to CSV — walk all issues, write via `csv.writer`; no new dependencies

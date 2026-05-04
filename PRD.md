# Legacy Report — Product Requirements Document

**Version:** 1.0 (MVP)
**Date:** May 4, 2026
**Status:** Draft

---

## 1. Overview

**Legacy Report** is a personal, terminal-based TUI (Terminal User Interface) application for managing a comic book collection. It runs in the terminal as an interactive menu-driven app. The primary organizing principle of the collection is the **Legacy (LGY) issue number** — the canonical, continuous numbering that spans across a title's many reboots and relaunches.

---

## 2. Goals

- Provide a fast, simple, offline-first CLI tool for tracking personally owned comic book issues.
- Pull rich metadata from the ComicVine API and cache it locally to avoid redundant API calls.
- Support the nuanced reality of modern comic numbering (non-sequential issues, series restarts, legacy numbering).
- Be usable without an internet connection after initial metadata fetch.

---

## 3. Non-Goals (MVP)

The following are explicitly out of scope for v1.0:

- Export to PDF, CSV, or other file formats
- Bulk import from spreadsheet or external data source
- Collection value / pricing tracking
- Condition grading
- Physical location tracking (box/shelf)
- Variant cover tracking
- Multi-user or networked access
- A web or mobile interface

---

## 4. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Excellent CLI/TUI ecosystem, readable, learnable |
| TUI Framework | [InquirerPy](https://github.com/kazhala/InquirerPy) | Interactive prompts, menus, fuzzy search |
| Terminal Rendering | [Rich](https://github.com/Textualize/rich) | Beautiful tables, panels, formatted output |
| CLI Entry Point | [Typer](https://typer.tiangolo.com/) | Type-hint-driven CLI, auto help text |
| Database | SQLite | Zero-setup, single file, personal-scale |
| ORM | [SQLModel](https://sqlmodel.tiangolo.com/) | Combines SQLAlchemy + Pydantic, pairs with Typer |
| HTTP Client | [httpx](https://www.python-httpx.org/) | Modern async-capable HTTP client |
| Config Storage | `~/.config/legacy-report/config.json` | User API key, preferences |

---

## 5. Data Model

### 5.1 Series

Represents a distinct run of a comic title. A title like "Daredevil" may have many Series entries (one per relaunch).

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `title` | TEXT | e.g., `Daredevil` |
| `start_year` | INTEGER | Disambiguates relaunches, e.g., `1998`, `2019` |
| `publisher` | TEXT | e.g., `Marvel`, `DC` |
| `comicvine_id` | TEXT | ComicVine volume ID, nullable |
| `description` | TEXT | From ComicVine, nullable |
| `created_at` | DATETIME | Local record creation time |

**Unique constraint:** `(title, start_year)`

> Example: `Daredevil (1964)`, `Daredevil (1998)`, `Daredevil (2019)` are three separate Series rows.

---

### 5.2 Issue

Represents a single comic book issue that the user owns.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `series_id` | INTEGER FK | References `Series.id` |
| `issue_number` | TEXT | Stored as text: handles `0`, `1.5`, `-1`, `1/2` |
| `legacy_number` | TEXT | LGY number, e.g., `#613`. Nullable — not all titles have LGY |
| `publication_date` | DATE | Most important field — the canonical date of record |
| `story_title` | TEXT | Story arc or issue title from ComicVine, nullable |
| `description` | TEXT | Issue synopsis from ComicVine, nullable |
| `cover_image_url` | TEXT | ComicVine cover image URL, nullable |
| `writer` | TEXT | From ComicVine, nullable |
| `artist` | TEXT | From ComicVine, nullable |
| `comicvine_id` | TEXT | ComicVine issue ID, nullable |
| `created_at` | DATETIME | Local record creation time |
| `updated_at` | DATETIME | Last local edit time |

> **Key design note:** `issue_number` is TEXT, not INTEGER. Modern comics use non-sequential values like `0`, `1.5`, `1/2`, and `-1`. `publication_date` is the true chronological anchor. `legacy_number` (LGY) is the collector's canonical reference across all series restarts.

---

### 5.3 ComicVine Cache

Stores raw API responses to avoid hitting the rate limit (100 requests/hour).

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `cache_key` | TEXT UNIQUE | Hash or composite of endpoint + query params |
| `response_json` | TEXT | Full JSON response body |
| `fetched_at` | DATETIME | When the cache was populated |
| `ttl_hours` | INTEGER | Default: 24 hours |

Cache lookup happens before any API call. Stale entries (older than `ttl_hours`) trigger a fresh API fetch.

---

## 6. Application Flow

### 6.1 Entry Point

User runs `legacy-report` in the terminal. The app checks for a valid ComicVine API key in config. If missing, it prompts setup. Otherwise, it launches the **Main Menu**.

---

### 6.2 Main Menu

```
╔══════════════════════════════╗
║      LEGACY REPORT  v1.0     ║
╚══════════════════════════════╝

  1) Search My Collection
  2) Add Issue
  3) Edit Issue
  4) Delete Issue
  5) Setup / Configuration
  6) Quit
```

---

### 6.3 Search My Collection

1. User enters a search term (title name).
2. App queries local SQLite database — no API call.
3. Results displayed in a Rich table, sorted by `publication_date`.
4. User can select an issue to view its full detail screen.

**Table columns:** Series | Issue # | LGY # | Publication Date | Story Title | Publisher

---

### 6.4 Add Issue

1. User enters a title to search (e.g., `Daredevil`).
2. App checks ComicVine cache → if stale/missing, calls ComicVine API.
3. A list of matching **series/volumes** is displayed (e.g., `Daredevil (1964)`, `Daredevil (1998)`).
4. User selects the correct series.
5. A list of **issues** within that series is displayed.
6. User selects the specific issue they own.
7. Metadata is pre-populated from ComicVine. User can confirm or edit any field.
8. Issue is saved to local SQLite database.

---

### 6.5 Edit Issue

1. User searches their collection (same as Search flow).
2. User selects an issue to edit.
3. Fields are presented as editable prompts pre-filled with existing values.
4. Changes are saved; `updated_at` is refreshed.

---

### 6.6 Delete Issue

1. User searches their collection.
2. User selects an issue.
3. Confirmation prompt: `Delete Daredevil #1 (1998)? [y/N]`
4. On confirm, record is removed from database.

---

### 6.7 Setup / Configuration

```
  1) Set ComicVine API Key
  2) View current config
  3) Back
```

- API key is stored in `~/.config/legacy-report/config.json`.
- Key is validated with a lightweight test call to ComicVine on save.

---

## 7. ComicVine API Integration

- **Base URL:** `https://comicvine.gamespot.com/api/`
- **Auth:** API key passed as query parameter `api_key`
- **Rate limit:** 100 requests/hour — cache-first strategy enforces this
- **Key endpoints used:**
  - `GET /volumes/` — search for series by title
  - `GET /issues/` — search issues within a volume
  - `GET /issue/{id}/` — get full metadata for a specific issue
- **Cache TTL:** 24 hours (configurable in config.json)
- **Cache miss behavior:** Fetch from API, store response, return data

---

## 8. Configuration File

Location: `~/.config/legacy-report/config.json`

```json
{
  "comicvine_api_key": "your-key-here",
  "cache_ttl_hours": 24,
  "db_path": "~/.local/share/legacy-report/collection.db"
}
```

---

## 9. MVP Command Summary

| Action | Description |
|---|---|
| `legacy-report` | Launch the interactive TUI menu |
| `legacy-report --version` | Print version info |
| `legacy-report --help` | Print help |

All primary functionality is accessed through the interactive menu, not CLI flags.

---

## 10. Project Structure

```
legacy-report/
├── PRD.md
├── README.md
├── pyproject.toml           # Project metadata, dependencies
├── legacy_report/
│   ├── __init__.py
│   ├── main.py              # Typer entry point, launches TUI
│   ├── menu.py              # Main menu loop (InquirerPy)
│   ├── models.py            # SQLModel table definitions
│   ├── db.py                # Database init, session management
│   ├── comicvine.py         # ComicVine API client + cache logic
│   ├── config.py            # Config file read/write
│   └── display.py           # Rich tables and panels
└── tests/
    └── __init__.py
```

---

## 11. Future Considerations (Post-MVP)

- Export collection to CSV / PDF report
- Bulk import from CSV
- Condition, location, and purchase price fields
- Wishlist / want list tracking
- Cover image display in terminal (Kitty/iTerm2 image protocol)
- Collection value tracking via pricing APIs

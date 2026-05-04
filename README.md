# Legacy Report

A terminal-based TUI for managing your comic book collection using **Legacy (LGY) numbering** — the canonical, continuous issue numbers that span a title's reboots and relaunches.

## Requirements

- Python 3.11+
- A free [ComicVine API key](https://comicvine.gamespot.com/api/)

## Setup

1. **Clone the repo**

   ```bash
   git clone <repo-url>
   cd legacy-report
   ```

2. **Install dependencies**

   **Option A — `pipx` (recommended for end users)**

   `pipx` installs CLI tools in isolated environments automatically.

   ```bash
   pipx install .
   ```

   > Install pipx if needed: `sudo apt install pipx`

   **Option B — virtual environment (recommended for development)**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

   > On modern Linux, running `pip install` outside a virtual environment is blocked by the OS. Always activate your venv first (`source .venv/bin/activate`) before running `pip`.

2. **Configure your ComicVine API key**

   On first run the app will prompt you to enter your API key. It is saved to `~/.config/legacy-report/config.json`.

   You can also set it manually:

   ```json
   // ~/.config/legacy-report/config.json
   {
     "comicvine_api_key": "YOUR_API_KEY_HERE"
   }
   ```

## Running

```bash
legacy-report
```

Check the version:

```bash
legacy-report --version
```

## Data Storage

| Path | Contents |
|---|---|
| `~/.config/legacy-report/config.json` | API key and preferences |
| `~/.local/share/legacy-report/collection.db` | SQLite collection database |

# ia-search

Interactive CLI to search Archive.org for files, browse results, inspect per-item files and hashes, search hash on rg-adguard.net, and download via aria2 (preferred) or PySmartDL.

## Usage

- After install:
  - `ia-search -q "Ubuntu 22.04"`

## Install

- `git clone https://github.com/domgregori/internetarchive-search.git`
- `uv run ia-search.py -q "search term"`

OR

- `python ia-search.py -q "search"` _requires dependencies to be installed_
  - `pip install .`

### Quick Examples

- Most downloaded Ubuntu ISO results (default mediatype: software):
  - `ia-search -q "Ubuntu 22.04 iso" --rows 50 --sort downloads --order desc`
- Generic text query with default sort:
  - `ia-search -q "Beatles"`
- Date range filtering (inclusive):
  - `ia-search -q "Ubuntu" --date-after 2022-01-01 --date-before 2023-12-31`
  - If not provided, `--date-after` defaults to `1970-01-01` and `--date-before` defaults to today (UTC).
- Request different fields (identifier, downloads, title are default):
  - `ia-search -q "Ubuntu" --fields identifier downloads title`
- Option to prefer ISOs (adds `description:(iso OR cd-rom)`):
  - `ia-search -q "Ubuntu 22.04" --iso`
- Add custom description terms (OR’ed together):
  - `ia-search -q "Ubuntu 22.04" --description-term iso --description-term cd-rom`

### Actions

- filter inline (`[/]term`, `[r]` to reset), or start a new search (`[s]`).
- Enter an item to view files; filter files similarly. Select a file to view details.
- File details actions: `[d]` download (aria2 preferred), `[h]` hash search (rg-adguard), `[o]` open download URL, `[c]` copy download URL, `[b]` back, `[q]` quit.
- Results/files footers show actions in bracketed style, e.g. `( Page: 1/3 [n]ext [p]rev [/] filter [r]eset [q]uit )`.

Example: Searching for a flac album

- `ia_search.py -q "Beatles" --sort "downloads desc" --mediatype audio --description-term flac`

### Downloading files

- Downloads from details menu (`[d]`).
- Filter files before selection:
  - `--ext iso` or `--file-contains desktop`
- Choose download directory: `--download-dir ./downloads`
- Aria2 control:
  - `--aria2-path /usr/bin/aria2c`, `--max-connections 16`, `--no-aria2`
  - Non-verbose runs aria2 with minimal console output.

## Options

- `-q, --query` Search string for Archive.org.
- `--mediatype` Restrict results (e.g., `software`, `audio`, `movies`).
- `--rows` Rows per page (default: 10).
- `--page` Page number (default: 1).
- `--sort` Sort expression (e.g., `downloads desc`, `date asc`).
- `--order` Optional `asc|desc` to pair with a bare `--sort`.
- `--list-sort-options` List curated sort options and exit.
- `--list-field-options` List curated field options and exit.
- `--fields` Fields to request (defaults to a curated set).
- `--iso` Add `description:(iso OR cd-rom)` to the query.
- `--description-term` Add term(s) to `description:(...)` (repeatable).
- `--ext` Filter files by extension in details view (e.g., `iso`, `zip`).
- `--no-human` Show raw bytes instead of human-readable sizes.
- `--hash` Hash column to display (`sha1|md5`; default: `sha1`).
- `--download-dir` Directory to save downloads (default: `./downloads`).
- `--file-contains` Filter files by substring before selection.
- `--aria2-path` Path to `aria2c` binary.
- `--max-connections` Max connections per file for aria2 (default: `16`).
- `--no-aria2` Force PySmartDL fallback instead of aria2.
- `--verbose` Increase verbosity (`-v`, `-vv`).
- `--long-columns` Disable truncation/wrapping in tables.
- `--no-terminal-aware` Disable terminal width aware sizing.
- `--date-before` End date `YYYY-MM-DD`; defaults to today (UTC).
- `--date-after` Start date `YYYY-MM-DD`; defaults to `1970-01-01`.

## Interactive Actions

- Results: `[n]ext [p]rev [/] filter [r]eset [s]earch [q]uit`
- Files: `[n]ext [p]rev [/] filter [r]eset [b]ack [q]uit [c]opy page [o]pen page`
- File info: `[d]ownload [h]ash search (on rg-adguard) [o]pen (download URL) [c]opy (download URL) [b]ack [q]uit`

## Notes

This tool was made in a day _"vibe coding"_. as much as I hate that phrase, I did enjoy the process. It from the frustration of wanting to download OS ISOs but I wanted to check if the ISO matched the official image. So this tool allows you to search for files on Internet Archive, search the hash on rg-adguard.net to see if it's a match, and download the files via aria2 or PySmartDL.

Given that this was made in a day, it's a starting point and has bugs but gets the job done.

## Development

### Shell Completions

- Bash:
  - Source ad hoc: `source completions/ia-search.bash`
  - Or install:
    - System: copy to `/etc/bash_completion.d/ia-search`
    - User: copy to `~/.local/share/bash-completion/completions/ia-search`
- Zsh:
  - Copy `completions/_ia-search` to a folder in `$fpath` (e.g., `~/.zsh/completions`)
  - Initialize: `autoload -U compinit && compinit`

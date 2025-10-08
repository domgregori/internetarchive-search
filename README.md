# ia-search

CLI to query Archive.org Advanced Search and display results in a colored table, with an interactive mode to inspect files, view all hashes, and download via aria2 (preferred) or PySmartDL.

## Install (uv)

- Editable install:
  - `uv pip install -e .`
- Or run without install:
  - `uv run ia_search.py -q "Ubuntu 22.04" --iso -i`

## Usage

- After install:
  - `ia-search -q "Ubuntu 22.04 iso"`

### Quick Examples

- Most downloaded Ubuntu ISO results (default mediatype: software):
  - `ia-search -q "Ubuntu 22.04 iso" --rows 50 --sort downloads --order desc`
- Generic text query with default sort:
  - `ia-search -q "Beatles"`
- Show the generated API URL:
  - `ia-search -q "Ubuntu 22.04 iso" --print-url`
- Request different fields (identifier, downloads, title are default):
  - `ia-search -q "Ubuntu" --fields identifier downloads title`
  - Rich default fields are included by default (identifier,title,creator,date,publicdate,downloads,mediatype,item_size,month,week,year,language,num_reviews,subject,publisher,rights,licenseurl)
 - Prefer ISOs by description terms (adds `description:(iso OR cd-rom)`):
   - `ia-search -q "Ubuntu 22.04" --iso`
 - Add custom description terms (OR’ed together):
   - `ia-search -q "Ubuntu 22.04" --description-term iso --description-term cd-rom`
Note: Subject filters are not used by default; `--iso` adds description:(iso OR cd-rom).

### Interactive mode

- The tool always runs interactively. Browse and inspect a result’s files and hashes:
  - `ia-search -q "Ubuntu 22.04" --iso`
- Print raw JSON for the selected item:
  - `ia-search -q "Ubuntu 22.04 iso" -i --json`
- Add verbose logging:
  - `ia-search -q "Ubuntu 22.04 iso" -i -v`
- Filter files by extension and show sizes human-readably (default):
  - `ia-search -q "Ubuntu 22.04 iso" -i --ext iso`
- Show raw byte sizes instead of human-readable:
  - `ia-search -q "Ubuntu 22.04 iso" -i --no-human`
- Choose which hash to display (default sha1):
  - `ia-search -q "Ubuntu 22.04 iso" -i --hash md5`
  - `ia-search -q "Ubuntu 22.04 iso" -i --hash sha256`

### Downloading files

- Downloads happen from the per-file details menu (`d`).
- Filter files before selection:
  - `ia-search -q "Ubuntu 22.04 iso" -i --ext iso`
  - `ia-search -q "Ubuntu 22.04 iso" -i --file-contains desktop`
- Dry run (no download, just list URLs):
  - `ia-search -q "Ubuntu 22.04 iso" -i --dry-run`
- Choose download directory:
  - `ia-search -q "Ubuntu 22.04 iso" -i --download-dir /path/to/dir`
- Control aria2:
  - `--aria2-path /usr/bin/aria2c` to set binary path
  - `--max-connections 16` per file
  - `--no-aria2` to force PySmartDL fallback
  - Non-verbose mode runs aria2 with `--quiet --console-log-level=error`.

## Options

- `-q, --query` Search string for Archive.org `q` parameter (not required with `--list-sorts`)
- `--mediatype` Restrict to a mediatype (e.g. `software`, `audio`, `movies`)
- `--rows` Rows per page (default 10)
- `--page` Page number (default 1)
- `--sort` Sort key (accepts bare key like `downloads` or full expression like `downloads desc`; default `downloads desc`)
- `--order` Optional order `asc`|`desc` to pair with a bare `--sort`
- `--list-sorts` List curated supported sort options and exit
- `--fields` Fields to fetch (defaults to a rich set including identifier,title,creator,date,publicdate,downloads,mediatype,item_size,month,week,year,language,num_reviews,subject,publisher,rights,licenseurl)
- `--iso` Add `description:(iso OR cd-rom)` to the query
- `--description-term` Add term(s) to `description:(...)` (repeatable)
- Removed earlier subject convenience flags; use `--iso` to add `description:(iso OR cd-rom)`.
- `--print-url` Print the request URL
- `-i, --interactive` Interactive selection to view details
- `--json` In interactive mode, print the selected item’s raw JSON
- `-v, --verbose` Increase logging (repeat for more)

Interactive per-file actions
- `d` download (aria2 preferred; else PySmartDL)
- `r` search SHA1 on rg-adguard.net (shows first match name + link)
- `o` open download URL in browser
- `c` copy download URL to clipboard (prefers wl-copy; falls back to xclip/xsel/pbcopy/clip)
- `b` back to file list; `q` quit

## Notes

- Uses `requests` if available; falls back to `urllib` otherwise.
- Results table shows IDENTIFIER, DOWNLOADS, TITLE. Files table shows index, name (wrapped to 50 chars per line), size, and chosen hash. Selecting a file opens a details panel with all hashes and URLs.
- No JSONP callback is used; plain JSON API is requested.

## Development

- Run locally without uv:
  - `python ia_search.py -q "Ubuntu 22.04 iso"`
- Lint/format (optional, if you use these tools):
  - `ruff check .`
  - `black .`

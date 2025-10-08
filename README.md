# ia-search

Interactive CLI to query Archive.org Advanced Search, browse results, inspect per-item files and hashes, and download via aria2 (preferred) or PySmartDL.

## Install (uv)

- Editable install:
  - `uv pip install -e .`
- Or run without install:
  - `uv run ia_search.py -q "Ubuntu 22.04" --iso`

## Usage

- After install:
  - `ia-search -q "Ubuntu 22.04"`

### Quick Examples

- Most downloaded Ubuntu ISO results (default mediatype: software):
  - `ia-search -q "Ubuntu 22.04 iso" --rows 50 --sort downloads --order desc`
- Generic text query with default sort:
  - `ia-search -q "Beatles"`
- Show the generated API URL:
  - `ia-search -q "Ubuntu 22.04" --print-url`
- Date range filtering (inclusive):
  - `ia-search -q "Ubuntu" --date-after 2022-01-01 --date-before 2023-12-31`
  - If not provided, `--date-after` defaults to `1970-01-01` and `--date-before` defaults to today (UTC).
- Request different fields (identifier, downloads, title are default):
  - `ia-search -q "Ubuntu" --fields identifier downloads title`
  - Rich default fields are included by default (identifier,title,creator,date,publicdate,downloads,mediatype,item_size,month,week,year,language,num_reviews,subject,publisher,rights,licenseurl)
- Prefer ISOs by description terms (adds `description:(iso OR cd-rom)`):
  - `ia-search -q "Ubuntu 22.04" --iso`
- Add custom description terms (OR’ed together):
  - `ia-search -q "Ubuntu 22.04" --description-term iso --description-term cd-rom`
    Note: Subject filters are not used; `--iso` adds description:(iso OR cd-rom).

### Interactive mode

- Always interactive: browse results, paginate, filter inline (`/term`, `r` to reset), or start a new search (`s`).
- Enter an item to view files; paginate and filter files similarly. Select a file to view details.
- File details actions: `d` download (aria2 preferred), `h` hash search (rg-adguard), `o` open download URL, `c` copy download URL, `b` back, `q` quit.
- Results/files footers show actions in bracketed style, e.g. `( Page: 1/3 [n]ext [p]rev [/] filter [r]eset [q]uit )`.

Example: Searching for a different type

- `ia_search.py -q "Beatles" --sort "downloads desc" --mediatype audio --description-term flac`

### Downloading files

- Downloads from the per-file details menu (`d`).
- Filter files before selection:
  - `--ext iso` or `--file-contains desktop`
- Choose download directory: `--download-dir ./downloads` (created on demand)
- Aria2 control:
  - `--aria2-path /usr/bin/aria2c`, `--max-connections 16`, `--no-aria2`
  - Non-verbose runs aria2 with minimal console output.

## Options

- `-q, --query` Search string for Archive.org `q` parameter (not required with `--list-sort-options`)
- `--mediatype` Restrict to a mediatype (e.g. `software`, `audio`, `movies`)
- `--rows` Rows per page (default 10)
- `--page` Page number (default 1)
- `--sort` Sort key (accepts bare key like `downloads` or full expression like `downloads desc`; default `downloads desc`)
- `--order` Optional order `asc`|`desc` to pair with a bare `--sort`
- `--list-sort-options` List curated supported sort options and exit
- `--fields` Fields to fetch (defaults to a rich set including identifier,title,creator,date,publicdate,downloads,mediatype,item_size,month,week,year,language,num_reviews,subject,publisher,rights,licenseurl)
- `--iso` Add `description:(iso OR cd-rom)` to the query
- `--description-term` Add term(s) to `description:(...)` (repeatable)
- Removed earlier subject convenience flags; use `--iso` to add `description:(iso OR cd-rom)`.
- `--print-url` Print the request URL
- (Always interactive; no `-i`)
- `-v, --verbose` Increase logging (repeat for more)

Interactive actions (highlights)

- Results: `[n]ext [p]rev [/] filter [r]eset [s]earch [q]uit`
- Files: `[n]ext [p]rev [/] filter [r]eset [b]ack [q]uit [c]opy page [o]pen page`
- File info: `[d]ownload [h]ash search [o]pen (download URL) [c]opy (download URL) [b]ack [q]uit`

## Notes

- Uses `requests` if available; falls back to `urllib` otherwise.
- Results table shows IDENTIFIER, DOWNLOADS, TITLE. Files table shows index, name (wrapped to 50 chars per line), size, and chosen hash. Selecting a file opens a details panel with all hashes and URLs.
- No JSONP callback is used; plain JSON API is requested.

## Development

- Run locally without uv:
  - `python ia_search.py -q "Ubuntu 22.04"`
- Lint/format (optional, if you use these tools):
  - `ruff check .`
  - `black .`

### Shell Completions

- Bash:
  - Source ad hoc: `source completions/ia-search.bash`
  - Or install:
    - System: copy to `/etc/bash_completion.d/ia-search`
    - User: copy to `~/.local/share/bash-completion/completions/ia-search`
- Zsh:
  - Copy `completions/_ia-search` to a folder in `$fpath` (e.g., `~/.zsh/completions`)
  - Add to `~/.zshrc`: `fpath=(~/.zsh/completions $fpath)`
  - Initialize: `autoload -U compinit && compinit`

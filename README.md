# ia-search

CLI to query Archive.org Advanced Search and display results in a colored table.

## Install (uv)

- Editable install:
  - `uv pip install -e .`
- Or run without install:
  - `uv run ia_search.py -q "Ubuntu 22.04 iso"`

## Usage

- After install:
  - `ia-search -q "Ubuntu 22.04 iso"`

### Examples

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
 - Filter by subject tags (OR semantics):
   - `ia-search -q "Ubuntu 22.04" --subject iso`
   - Shortcut for ISO subject: `ia-search -q "Ubuntu 22.04" --subject-iso`

### Interactive mode

- Browse and inspect a result’s files and hashes:
  - `ia-search -q "Ubuntu 22.04 iso" -i`
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

- ### Downloading files

- Enter download flow after selecting an item (uses aria2 directly if available, else PySmartDL):
  - `ia-search -q "Ubuntu 22.04 iso" -i --download`
- Filter files before selection:
  - `ia-search -q "Ubuntu 22.04 iso" -i --download --ext iso`
  - `ia-search -q "Ubuntu 22.04 iso" -i --download --file-contains desktop`
- Dry run (no download, just list URLs):
  - `ia-search -q "Ubuntu 22.04 iso" -i --download --dry-run`
- Choose download directory:
  - `ia-search -q "Ubuntu 22.04 iso" -i --download --download-dir /path/to/dir`
- Control aria2:
  - `--aria2-path /usr/bin/aria2c` to set binary path
  - `--max-connections 16` per file
  - `--no-aria2` to force PySmartDL fallback
  - While downloading: press `x` to cancel, `q` to quit

## Options

- `-q, --query` Search string for Archive.org `q` parameter
- `--mediatype` Restrict to a mediatype (e.g. `software`, `audio`, `movies`)
- `--rows` Rows per page (default 50)
- `--page` Page number (default 1)
- `--sort` Sort key (accepts bare key like `downloads` or full expression like `downloads desc`; default `downloads desc`)
- `--order` Optional order `asc`|`desc` to pair with a bare `--sort`
- `--list-sorts` List curated supported sort options and exit
- `--fields` Fields to fetch (default: `identifier downloads title`)
- `--iso` Add `description:(iso OR cd-rom)` to the query
- `--description-term` Add term(s) to `description:(...)` (repeatable)
- `--subject` Add a subject term (repeatable). Example: `--subject iso`
- `--subject-iso` Convenience flag to add `subject:(iso)`
- `--print-url` Print the request URL
- `-i, --interactive` Interactive selection to view details
- `--json` In interactive mode, print the selected item’s raw JSON
- `-v, --verbose` Increase logging (repeat for more)

## Notes

- Uses `requests` if available; falls back to `urllib` otherwise.
- Outputs a colored table with columns: IDENTIFIER, DOWNLOADS, TITLE.
- No JSONP callback is used; plain JSON API is requested.

## Development

- Run locally without uv:
  - `python ia_search.py -q "Ubuntu 22.04 iso"`
- Lint/format (optional, if you use these tools):
  - `ruff check .`
  - `black .`

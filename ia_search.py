#!/usr/bin/env python3
"""
Simple CLI to search archive.org advanced search and print results in a colored table.

Usage:
  python ia_search.py -q "Ubuntu 22.04 iso" --mediatype software --rows 50 --page 1 --sort "downloads desc"

Notes:
  - Network access is required to query archive.org.
  - Results print identifier and downloads if present.
"""

import argparse
import json
import sys
import textwrap
import shutil
import subprocess
import time
import socket
from contextlib import closing
from dataclasses import dataclass
from typing import List, Optional, Tuple
import os
import select
try:
    import msvcrt  # type: ignore
except Exception:
    msvcrt = None

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # fallback to urllib if requests is unavailable

import urllib.parse
import urllib.request


# ANSI color helpers
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m]"  # not used; keep palette minimal
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{Color.RESET}"


def read_key_nonblocking() -> Optional[str]:
    if os.name == 'nt' and msvcrt is not None:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            return ch
        return None
    # POSIX
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], 0)
        if rlist:
            ch = sys.stdin.read(1)
            return ch
    except Exception:
        return None
    return None


@dataclass
class Item:
    identifier: str
    downloads: Optional[int] = None
    title: Optional[str] = None


ALLOWED_SORT = {
    # common useful sorts
    "downloads desc",
    "downloads asc",
    "week desc",
    "week asc",
    "month desc",
    "month asc",
    "year desc",
    "year asc",
    "publicdate desc",
    "publicdate asc",
    "date desc",
    "date asc",
    "titleSorter desc",
    "titleSorter asc",
    "creatorSorter desc",
    "creatorSorter asc",
    "identifier asc",
    "identifier desc",
    "avg_rating desc",
    "avg_rating asc",
    "item_size desc",
    "item_size asc",
    # random is supported by IA
    "random desc",
    "random asc",
}

def list_sorts() -> str:
    lines = [color("Supported sort keys (curated):", Color.BOLD)]
    for s in sorted(ALLOWED_SORT):
        lines.append(f"  - {s}")
    return "\n".join(lines)


def build_url(
    q: str,
    mediatype: Optional[str],
    rows: int,
    page: int,
    sort: Optional[str],
    fields: List[str],
    description_terms: Optional[List[str]] = None,
) -> str:
    base = "https://archive.org/advancedsearch.php"
    # Build query
    q_parts = [f"({q})"]
    if mediatype:
        q_parts.append(f"mediatype:({mediatype})")
    if description_terms:
        desc = " OR ".join(description_terms)
        q_parts.append(f"description:({desc})")
    q_full = " AND ".join(q_parts)

    params = []  # keep order stable
    params.append(("q", q_full))
    for f in fields:
        params.append(("fl[]", f))
    if sort:
        params.append(("sort[]", sort))
    else:
        params.append(("sort[]", "downloads desc"))
    # add two extra empty sort[] to mirror sample URL (not strictly needed)
    params.append(("sort[]", ""))
    params.append(("sort[]", ""))
    params.append(("rows", str(rows)))
    params.append(("page", str(page)))
    params.append(("output", "json"))
    # no JSONP callback for CLI
    params.append(("save", "yes"))

    return base + "?" + urllib.parse.urlencode(params, doseq=True)


def fetch_json(url: str, debug: bool = False) -> dict:
    if debug:
        print(color(f"GET {url}", Color.MAGENTA), file=sys.stderr)
    if requests is not None:
        resp = requests.get(url, timeout=20)
        if debug:
            print(color(f"Status {resp.status_code}", Color.DIM), file=sys.stderr)
        resp.raise_for_status()
        data = resp.text
        try:
            js = resp.json()
        except Exception:
            if debug:
                print(color("Response not JSON; first 500 bytes:", Color.YELLOW), file=sys.stderr)
                print(data[:500], file=sys.stderr)
            raise
        return js
    # urllib fallback
    with urllib.request.urlopen(url, timeout=20) as r:  # nosec B310 (fixed host)
        data = r.read()
    if debug:
        print(color(f"Bytes received: {len(data)}", Color.DIM), file=sys.stderr)
    return json.loads(data.decode("utf-8"))


def parse_items(payload: dict) -> List[Item]:
    response = payload.get("response", {})
    docs = response.get("docs", [])
    items: List[Item] = []
    for d in docs:
        identifier = d.get("identifier")
        if not identifier:
            continue
        downloads = d.get("downloads")
        title = d.get("title")
        items.append(Item(identifier=str(identifier), downloads=downloads, title=title))
    return items


def format_table(items: List[Item]) -> str:
    if not items:
        return color("No results.", Color.YELLOW)

    # determine widths
    id_width = max(10, *(len(i.identifier) for i in items))
    title_width = min(60, max(5, *(len(i.title or "") for i in items)))
    # downloads field can be missing
    dl_values = [i.downloads for i in items if i.downloads is not None]
    dl_width = max(9, len(str(max(dl_values))) if dl_values else 9)

    # header with index column
    header = (
        color("#".rjust(3), Color.BOLD)
        + "  "
        + color("IDENTIFIER".ljust(id_width), Color.BOLD)
        + "  "
        + color("DOWNLOADS".rjust(dl_width), Color.BOLD)
        + "  "
        + color("TITLE".ljust(title_width), Color.BOLD)
    )
    sep = "-" * (3 + id_width + dl_width + title_width + 6)

    lines = [header, sep]
    for idx, it in enumerate(items, 1):
        title = (it.title or "").replace("\n", " ")
        if len(title) > title_width:
            title = title[: title_width - 1] + "…"
        dl = "-" if it.downloads is None else str(it.downloads)
        idxs = color(str(idx).rjust(3), Color.MAGENTA)
        ident = color(it.identifier.ljust(id_width), Color.BLUE)
        dlc = color(dl.rjust(dl_width), Color.GREEN)
        titlec = color(title.ljust(title_width), Color.DIM)
        lines.append(f"{idxs}  {ident}  {dlc}  {titlec}")
    return "\n".join(lines)


def prompt_index(n: int) -> Optional[int]:
    try:
        raw = input(
            color("Select a row number (or Enter to quit): ", Color.BOLD)
        ).strip()
    except EOFError:
        return None
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        print(color("Invalid number.", Color.YELLOW))
        return None
    if 1 <= idx <= n:
        return idx - 1
    print(color(f"Out of range 1..{n}", Color.YELLOW))
    return None


def parse_multi_select(raw: str, n: int) -> List[int]:
    sel: List[int] = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, _, b = part.partition('-')
            try:
                start = int(a)
                end = int(b)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for i in range(start, end + 1):
                if 1 <= i <= n:
                    sel.append(i - 1)
        else:
            try:
                i = int(part)
                if 1 <= i <= n:
                    sel.append(i - 1)
            except ValueError:
                continue
    # de-dup while preserving order
    seen = set()
    out: List[int] = []
    for i in sel:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def find_free_port(start: int = 6800, end: int = 6899) -> int:
    for port in range(start, end + 1):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return 6800


def build_file_url(details: dict, name: str) -> Optional[str]:
    server = details.get("server")
    dir_ = details.get("dir")
    if not server or not dir_:
        return None
    name = name.lstrip('/')
    return f"https://{server}{dir_}/{urllib.parse.quote(name)}"


# Removed JSON-RPC helpers; we now run aria2c directly


def fetch_item_details(identifier: str, debug: bool = False) -> dict:
    url = f"https://archive.org/details/{urllib.parse.quote(identifier)}?output=json"
    return fetch_json(url, debug=debug)


def _first(meta: dict, key: str) -> Optional[str]:
    v = meta.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    if isinstance(v, str):
        return v
    return None


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            if u == "B":
                return f"{int(size)} {u}"
            return f"{size:.1f} {u}"
        size /= 1024


def format_item_details(
    data: dict,
    ext_filter: Optional[str] = None,
    human: bool = True,
    hash_type: str = "sha1",
) -> str:
    metadata = data.get("metadata", {})
    files_obj = data.get("files", [])
    # Normalize files: API can return a dict keyed by path or a list
    if isinstance(files_obj, dict):
        files = [
            {"name": k.lstrip("/"), **(v or {})} for k, v in files_obj.items()
        ]
    else:
        files = files_obj
    # Header info
    title = _first(metadata, "title") or _first(metadata, "identifier") or "(no title)"
    creator = _first(metadata, "creator") or "(unknown)"
    date = _first(metadata, "date") or _first(metadata, "publicdate") or "(unknown)"
    item_info = data.get("item", {}) or {}
    total_size = item_info.get("item_size")
    files_count = item_info.get("files_count")
    lines = []
    lines.append(color(str(title), Color.BOLD))
    lines.append(f"Creator: {creator}")
    lines.append(f"Date: {date}")
    if total_size is not None:
        try:
            lines.append(f"Total Size: {int(total_size):,} bytes")
        except Exception:
            lines.append(f"Total Size: {total_size}")
    if files_count is not None:
        lines.append(f"Files: {files_count}")
    lines.append("")
    # Files table
    if not files:
        lines.append(color("No file list available.", Color.YELLOW))
        return "\n".join(lines)

    # optional filter by file extension (case-insensitive, e.g., 'iso' or '.iso')
    if ext_filter:
        ef = ext_filter.lower().lstrip(".")
        files = [f for f in files if f.get("name", "").lower().endswith("." + ef)]

    name_w = max(10, *(len(f.get("name", "")) for f in files)) if files else 10
    size_w = 12
    hash_label = hash_type.upper()
    hash_w = max(8, len(hash_label), 40)
    header = (
        color("FILE".ljust(name_w), Color.BOLD)
        + "  "
        + color("SIZE".rjust(size_w), Color.BOLD)
        + "  "
        + color(hash_label.ljust(hash_w), Color.BOLD)
    )
    lines.append(header)
    lines.append("-" * (name_w + size_w + hash_w + 4))
    for f in files:
        name = f.get("name", "")
        size = f.get("size")
        md5 = f.get("md5")
        sha1 = f.get("sha1")
        sha256 = f.get("sha256") or f.get("sha256sum")
        if size in (None, ""):
            size_s = "-"
        else:
            try:
                size_i = int(size)
                size_s = human_size(size_i) if human else f"{size_i:,}"
            except Exception:
                size_s = str(size)
        if hash_type == "md5":
            hash_s = md5 or "-"
        elif hash_type == "sha256":
            hash_s = sha256 or "-"
        else:  # default sha1
            hash_s = sha1 or "-"
        lines.append(
            f"{name.ljust(name_w)}  {size_s.rjust(size_w)}  {hash_s[:hash_w].ljust(hash_w)}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Search archive.org and print results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              ia_search.py -q "Ubuntu 22.04 iso" --mediatype software --rows 25
              ia_search.py -q "Beatles" --sort "downloads desc"
            """
        ),
    )
    p.add_argument(
        "-q",
        "--query",
        required=False,
        help="Search query for 'q' (e.g., Ubuntu 22.04 iso)",
    )
    p.add_argument(
        "--mediatype",
        default="software",
        help="Restrict mediatype, e.g. software, audio, movies (default: software)",
    )
    p.add_argument("--rows", type=int, default=50, help="Rows per page (default: 50)")
    p.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    p.add_argument(
        "--sort",
        default="downloads desc",
        help="Sort expression (e.g., 'downloads desc', 'date desc')",
    )
    p.add_argument(
        "--order",
        choices=["asc", "desc"],
        help="Optional sort order if using --sort without order",
    )
    p.add_argument(
        "--list-sorts",
        action="store_true",
        help="List curated supported sort options and exit",
    )
    p.add_argument(
        "--fields",
        nargs="*",
        default=[
            "identifier",
            "title",
            "creator",
            "date",
            "publicdate",
            "downloads",
            "mediatype",
            "item_size",
            "month",
            "week",
            "year",
            "language",
            "num_reviews",
            "subject",
            "publisher",
            "rights",
            "licenseurl",
        ],
        help=(
            "Fields to request; defaults to a rich set including "
            "identifier,title,creator,date,publicdate,downloads,mediatype,item_size,month,week,year,language,num_reviews,subject,publisher,rights,licenseurl"
        ),
    )
    p.add_argument(
        "--print-url",
        action="store_true",
        help="Print the generated URL before results",
    )
    p.add_argument(
        "--iso",
        action="store_true",
        help="Convenience: add description:(iso OR cd-rom) to the query",
    )
    p.add_argument(
        "--description-term",
        action="append",
        dest="description_terms",
        help="Add a term to description:(...) clause (repeatable)",
    )
    p.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive mode: select a result to view details",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="In interactive mode, print raw item JSON instead of a table",
    )
    p.add_argument(
        "--ext",
        help="Filter files by extension in details view (e.g., iso, zip)",
    )
    p.add_argument(
        "--no-human",
        action="store_true",
        help="Disable human-readable sizes in details (show raw bytes)",
    )
    p.add_argument(
        "--hash",
        choices=["sha1", "md5", "sha256"],
        default="sha1",
        help="Hash column to display in details (default: sha1)",
    )
    # Download-related flags
    p.add_argument(
        "--download",
        action="store_true",
        help="After selecting an item (-i), select files to download",
    )
    p.add_argument(
        "--download-dir",
        default=".",
        help="Directory to save downloads (default: current dir)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned download URLs but do not download",
    )
    p.add_argument(
        "--file-contains",
        help="Filter files by substring (case-insensitive) before selection",
    )
    p.add_argument(
        "--aria2-path",
        help="Path to aria2c binary (auto-detected if in PATH)",
    )
    # Direct aria2 mode (no RPC)
    p.add_argument(
        "--max-connections",
        type=int,
        default=16,
        help="Max connections per file for aria2 (split/x)",
    )
    p.add_argument(
        "--no-aria2",
        action="store_true",
        help="Skip aria2 and use PySmartDL fallback",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv)",
    )

    args = p.parse_args(argv)
    # If requested, print sorts and exit
    if args.list_sorts:
        print(list_sorts())
        return 0

    # Normalize sort if --order given without order in --sort
    if args.order and (" asc" not in args.sort and " desc" not in args.sort):
        args.sort = f"{args.sort} {args.order}"

    # Validate sort against a curated allowlist if set
    if args.sort and args.sort not in ALLOWED_SORT:
        print(
            color(
                f"Warning: sort '{args.sort}' not in known list; continuing anyway",
                Color.YELLOW,
            ),
            file=sys.stderr,
        )

    if not args.query:
        print(color("Error: --query is required unless using --list-sorts", Color.YELLOW), file=sys.stderr)
        return 2

    # Build description terms
    desc_terms: List[str] = []
    if args.iso:
        desc_terms.extend(["iso", "cd-rom"])
    if args.description_terms:
        desc_terms.extend(args.description_terms)

    url = build_url(
        args.query,
        args.mediatype,
        args.rows,
        args.page,
        args.sort,
        args.fields,
        description_terms=(desc_terms or None),
    )
    if args.print_url:
        print(color("Request URL:", Color.MAGENTA), url)

    try:
        payload = fetch_json(url, debug=args.verbose > 0)
    except Exception as e:
        print(color(f"Request failed: {e}", Color.YELLOW), file=sys.stderr)
        return 2

    items = parse_items(payload)
    table = format_table(items)
    if args.interactive and items:
        while True:
            # show results with numbers
            numbered = []
            for idx, it in enumerate(items, 1):
                numbered.append(
                    f"{color(str(idx).rjust(3), Color.MAGENTA)}  {color(it.identifier, Color.BLUE)}  {color((it.title or ''), Color.DIM)}"
                )
            print("\n".join(numbered))
            sel = prompt_index(len(items))
            if sel is None:
                # Quit interactive loop
                print(table)
                break
            chosen = items[sel]
            try:
                details = fetch_item_details(chosen.identifier, debug=args.verbose > 0)
            except Exception as e:
                print(color(f"Details fetch failed: {e}", Color.YELLOW), file=sys.stderr)
                print(table)
                return 2
            if args.json:
                print(json.dumps(details, indent=2))
                # when viewing raw json, go back to results loop
                continue
            else:
                # Single colorful files table only
                print(format_item_details(details, ext_filter=args.ext, human=not args.no_human, hash_type=args.hash))
            # Enter download flow by default when interactive, unless explicitly disabled
            if args.download or (args.interactive and not args.json):
                files_obj = details.get("files", {})
                if isinstance(files_obj, dict):
                    files_list = [{"name": k.lstrip('/'), **(v or {})} for k, v in files_obj.items()]
                else:
                    files_list = files_obj or []
            # apply ext and contains filters again for selection
            if args.ext:
                ef = args.ext.lower().lstrip('.')
                files_list = [f for f in files_list if f.get('name','').lower().endswith('.'+ef)]
            if args.file_contains:
                sub = args.file_contains.lower()
                files_list = [f for f in files_list if sub in f.get('name','').lower()]
            if not files_list:
                print(color("No files match filters.", Color.YELLOW))
                return 0
            # Prompt with back option
            print()
            for idx, f in enumerate(files_list, 1):
                name = f.get('name','')
                size = f.get('size')
                hs = f.get(args.hash) or '-'
                try:
                    size_s = human_size(int(size)) if size not in (None, '') else '-'
                except Exception:
                    size_s = str(size) if size is not None else '-'
                print(f"{color(str(idx).rjust(3), Color.MAGENTA)}  {color(size_s.rjust(8), Color.GREEN)}  {color((hs if isinstance(hs,str) else str(hs))[:40].ljust(40), Color.DIM)}  {color(name, Color.BLUE)}")
            try:
                prompt = "Select files (e.g., 1,3,5-7), 'b' to go back, 'q' to quit: "
                raw = input(color(prompt, Color.BOLD))
            except EOFError:
                return 0
            raw = (raw or '').strip()
            if raw.lower() == 'q':
                # Quit interactive loop from files prompt
                break
            if raw.lower() == 'b':
                # Go back to results list
                continue
            indices = parse_multi_select(raw, len(files_list))
            if not indices:
                print(color("No valid selections.", Color.YELLOW))
                return 0
            selected = [files_list[i] for i in indices]
            # Build URLs
            urls = []
            torrents = []
            for f in selected:
                url = build_file_url(details, f.get('name',''))
                if url:
                    if url.lower().endswith('.torrent'):
                        torrents.append(url)
                    else:
                        urls.append(url)
            if not urls:
                print(color("No non-torrent URLs to download.", Color.YELLOW))
            print(color(f"Planned downloads to {args.download_dir}:", Color.BOLD))
            for u in torrents + urls:
                print(" - ", u)
            if args.dry_run:
                # after dry-run, return to results
                continue
            # Try aria2 unless disabled
            if not args.no_aria2:
                aria2_path = args.aria2_path or shutil.which('aria2c')
                if not aria2_path:
                    print(color("aria2 not found or disabled. Using PySmartDL fallback.", Color.YELLOW))
                else:
                    print(color("Found aria2", Color.GREEN))
                    cmd = [
                        aria2_path,
                        "--continue=true",
                        f"--max-connection-per-server={args.max_connections}",
                        f"--split={args.max_connections}",
                        f"--dir={args.download_dir}",
                    ]
                    cmd.extend(torrents)
                    cmd.extend(urls)
                    # Show controls hint and command if verbose
                    print(color("[x=cancel, q=quit]", Color.DIM))
                    if args.verbose:
                        print(color("Running aria2c:", Color.MAGENTA), " ".join(cmd))
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    try:
                        while True:
                            key = read_key_nonblocking()
                            if key:
                                k = key.lower()
                                if k == 'x':
                                    proc.terminate()
                                    print()
                                    print(color("Downloads canceled.", Color.YELLOW))
                                    break
                                if k == 'q':
                                    proc.terminate()
                                    print()
                                    print(color("Quitting.", Color.YELLOW))
                                    raise SystemExit(0)
                            line = proc.stdout.readline() if proc.stdout else ''
                            if not line:
                                if proc.poll() is not None:
                                    break
                                time.sleep(0.1)
                                continue
                            print(line, end='')
                        # After completion, return to results list
                        continue
                    finally:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
            # Fallback: PySmartDL
            if args.no_aria2:
                print(color("aria2 not found or disabled. Using PySmartDL fallback.", Color.YELLOW))
            print(color("[x=cancel, q=quit]", Color.DIM))
            try:
                from pySmartDL import SmartDL  # type: ignore
            except Exception:
                print(color("PySmartDL not installed; please install or use aria2.", Color.YELLOW))
                # back to results
                continue
            if torrents:
                print(color("Torrent downloads require aria2; skipping torrents in fallback.", Color.YELLOW))
            for u in urls:
                print(color(f"Downloading: {u}", Color.MAGENTA))
                obj = SmartDL(u, dest=args.download_dir)
                obj.start(blocking=False)
                # Poll with key handling
                while not obj.isFinished():
                    key = read_key_nonblocking()
                    if key:
                        k = key.lower()
                        if k == 'x':
                            obj.stop()
                            print()
                            print(color("Download canceled.", Color.YELLOW))
                            break
                        if k == 'q':
                            obj.stop()
                            print()
                            print(color("Quitting.", Color.YELLOW))
                            raise SystemExit(0)
                    time.sleep(0.2)
                if obj.isSuccessful():
                    print(color(f"Done: {u}", Color.GREEN))
                elif obj.get_errors():
                    print(color(f"Failed: {u}", Color.YELLOW))
            # After fallback downloads, continue to results list
            continue
    else:
        print(table)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

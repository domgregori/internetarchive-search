#!/usr/bin/env -S uv run
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
import html as _html
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
    if os.name == "nt" and msvcrt is not None:
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
                print(
                    color("Response not JSON; first 500 bytes:", Color.YELLOW),
                    file=sys.stderr,
                )
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
        raw = input(color("Select a row number (n=next, p=prev, 'q' to quit): ", Color.BOLD)).strip()
    except EOFError:
        return None
    if not raw:
        return None
    if raw.lower() == "q":
        return "q"  # type: ignore[return-value]
    if raw.lower() == "n":
        return "n"  # type: ignore[return-value]
    if raw.lower() == "p":
        return "p"  # type: ignore[return-value]
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
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
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
    name = name.lstrip("/")
    return f"https://{server}{dir_}/{urllib.parse.quote(name)}"


# Removed JSON-RPC helpers; we now run aria2c directly


def fetch_item_details(identifier: str, debug: bool = False) -> dict:
    url = f"https://archive.org/details/{urllib.parse.quote(identifier)}?output=json"
    return fetch_json(url, debug=debug)


def search_sha1_rg_adguard(sha1: str, debug: bool = False) -> Optional[Tuple[str, str]]:
    try:
        url = "https://files.rg-adguard.net/search"
        data = {"search": sha1}
        if debug:
            print(color("POST", Color.MAGENTA), url, data, file=sys.stderr)
        resp = requests.post(url, data=data, timeout=20)
    except Exception as e:
        if debug:
            print(color(f"Search request failed: {e}", Color.YELLOW), file=sys.stderr)
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    # Look for: <td class="desc">  <a href="...">NAME...</a></td>
    import re

    m = re.search(r'<td\s+class="desc"[^>]*>\s*<a\s+href="([^"]+)">([^<]+)</a>', text)
    if not m:
        return None
    href = m.group(1)
    name = _html.unescape(m.group(2))
    # Make absolute if needed
    if href.startswith("/"):
        href = urllib.parse.urljoin("https://files.rg-adguard.net", href)
    return name, href


def build_file_info(
    details: dict, f: dict, hash_type: str, human: bool, download_dir: str
) -> dict:
    name = f.get("name", "")
    size = f.get("size")
    try:
        size_i = int(size) if size not in (None, "") else None
    except Exception:
        size_i = None
    identifier = _first(details.get("metadata", {}), "identifier")
    info = {
        "name": name,
        "size": size_i,
        "size_h": human_size(size_i)
        if (human and isinstance(size_i, int))
        else (str(size) if size is not None else "-"),
        "md5": f.get("md5"),
        "sha1": f.get("sha1"),
        "format": f.get("format"),
        "mtime": f.get("mtime"),
        "crc32": f.get("crc32"),
        "url": build_file_url(details, name) or "",
        "page_url": f"https://archive.org/details/{identifier}" if identifier else "",
        "is_torrent": str(name).lower().endswith(".torrent"),
        "download_dir": download_dir,
        "preferred_hash": hash_type,
    }
    return info


def print_file_details(info: dict) -> None:
    print(color("\nFILE DETAILS", Color.BOLD))
    print(f"Name: {color(info['name'], Color.BLUE)}")
    print(
        f"Size: {color(info['size_h'], Color.GREEN)}"
        + (f"  ({info['size']:,} bytes)" if isinstance(info["size"], int) else "")
    )
    if info.get("format"):
        print(f"Format: {info['format']}")
    if info.get("mtime"):
        print(f"Modified: {info['mtime']}")
    if info.get("crc32"):
        print(f"CRC32: {info['crc32']}")
    print(f"MD5:   {info.get('md5') or '-'}")
    print(f"SHA1:  {info.get('sha1') or '-'}")
    print(f"Download URL: {color(info['url'], Color.MAGENTA)}")
    if info.get("page_url"):
        print(f"Page URL:     {color(info['page_url'], Color.MAGENTA)}")
    if info.get("is_torrent"):
        print(color("Note: This is a .torrent file.", Color.DIM))


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
        files = [{"name": k.lstrip("/"), **(v or {})} for k, v in files_obj.items()]
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
    lines.append("\n")
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
    # Files table
    if not files:
        lines.append(color("No file list available.", Color.YELLOW))
        return "\n".join(lines)

    # optional filter by file extension (case-insensitive, e.g., 'iso' or '.iso')
    if ext_filter:
        ef = ext_filter.lower().lstrip(".")
        files = [f for f in files if f.get("name", "").lower().endswith("." + ef)]

    idx_w = 3
    # Wrap filenames to a fixed width so long names don't break layout
    wrap_w = 50
    name_w = wrap_w
    size_w = 12
    hash_label = hash_type.upper()
    hash_w = max(8, len(hash_label), 40)
    header = (
        color("#".rjust(idx_w), Color.BOLD)
        + "  "
        + color("FILE".ljust(name_w), Color.BOLD)
        + "  "
        + color("SIZE".rjust(size_w), Color.BOLD)
        + "  "
        + color(hash_label.ljust(hash_w), Color.BOLD)
    )
    lines.append(header)
    lines.append("-" * (idx_w + name_w + size_w + hash_w + 6))
    for i, f in enumerate(files, 1):
        name = f.get("name", "")
        size = f.get("size")
        md5 = f.get("md5")
        sha1 = f.get("sha1")
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
        else:  # default sha1
            hash_s = sha1 or "-"
        # Wrap the filename into chunks of wrap_w, only the first line is numbered
        chunks = [name[x : x + wrap_w] for x in range(0, len(name), wrap_w)] or [""]
        idxc = color(str(i).rjust(idx_w), Color.MAGENTA)
        sizec = color(size_s.rjust(size_w), Color.GREEN)
        hashc = color(str(hash_s)[:hash_w].ljust(hash_w), Color.DIM)
        for j, chunk in enumerate(chunks):
            namec = color(chunk.ljust(name_w), Color.BLUE)
            if j == 0:
                lines.append(f"{idxc}  {namec}  {sizec}  {hashc}")
            else:
                # continuation lines: spaces for index/size/hash to keep alignment
                blank_idx = " " * idx_w
                blank_size = " " * size_w
                blank_hash = " " * hash_w
                lines.append(f"{blank_idx}  {namec}  {blank_size}  {blank_hash}")
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
    p.add_argument("--rows", type=int, default=10, help="Rows per page (default: 10)")
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
    # Always interactive now; flag removed
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
        choices=["sha1", "md5"],
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
        default="./downloads",
        help="Directory to save downloads (default: ./downloads)",
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
        print(
            color("Error: --query is required unless using --list-sorts", Color.YELLOW),
            file=sys.stderr,
        )
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
    if items:
        while True:
            # show results with numbers
            numbered = ["",]
            # Page-local indices 1..rows
            for idx, it in enumerate(items, 1):
                numbered.append(
                    f"{color(str(idx).rjust(3), Color.MAGENTA)}  {color(it.identifier, Color.BLUE)}  {color((it.title or ''), Color.DIM)}"
                )
            numbered.append(color(f"(page {args.page}, n = next, p = prev)", Color.DIM))
            print("\n".join(numbered))
            sel = prompt_index(len(items))
            if sel == "q":
                break
            if sel is None:
                # Quietly handle blank/invalid without extra print, or print once on EOF
                print(table)
                break
            if isinstance(sel, str) and sel == 'n':
                # fetch next page
                args.page += 1
                try:
                    next_url = build_url(
                        args.query,
                        args.mediatype,
                        args.rows,
                        args.page,
                        args.sort,
                        args.fields,
                        description_terms=(desc_terms or None),
                    )
                    payload = fetch_json(next_url, debug=args.verbose > 0)
                    items = parse_items(payload)
                    table = format_table(items)
                    continue
                except Exception as e:
                    print(color(f"Failed to load next page: {e}", Color.YELLOW))
                    continue
            if isinstance(sel, str) and sel == 'p':
                # fetch previous page if possible
                if args.page > 1:
                    args.page -= 1
                try:
                    prev_url = build_url(
                        args.query,
                        args.mediatype,
                        args.rows,
                        args.page,
                        args.sort,
                        args.fields,
                        description_terms=(desc_terms or None),
                    )
                    payload = fetch_json(prev_url, debug=args.verbose > 0)
                    items = parse_items(payload)
                    table = format_table(items)
                    continue
                except Exception as e:
                    print(color(f"Failed to load previous page: {e}", Color.YELLOW))
                    continue
            chosen = items[sel]
            try:
                details = fetch_item_details(chosen.identifier, debug=args.verbose > 0)
            except Exception as e:
                print(
                    color(f"Details fetch failed: {e}", Color.YELLOW), file=sys.stderr
                )
                print(table)
                return 2
            if args.json:
                print(json.dumps(details, indent=2))
                # when viewing raw json, go back to results loop
                continue
            else:
                # Item-scoped interactive files loop
                while True:
                    # Print only the single colorful files table
                    print(
                        format_item_details(
                            details,
                            ext_filter=args.ext,
                            human=not args.no_human,
                            hash_type=args.hash,
                        )
                    )
                    # Build file list for selection
                    files_obj = details.get("files", {})
                    if isinstance(files_obj, dict):
                        files_list = [
                            {"name": k.lstrip("/"), **(v or {})}
                            for k, v in files_obj.items()
                        ]
                    else:
                        files_list = files_obj or []
                    # apply ext and contains filters again for selection
                    if args.ext:
                        ef = args.ext.lower().lstrip(".")
                        files_list = [
                            f
                            for f in files_list
                            if f.get("name", "").lower().endswith("." + ef)
                        ]
                    if args.file_contains:
                        sub = args.file_contains.lower()
                        files_list = [
                            f for f in files_list if sub in f.get("name", "").lower()
                        ]
                    if not files_list:
                        print(color("No files match filters.", Color.YELLOW))
                        break
                    try:
                        # Single-file selection only
                        prompt = "Select a file (index), 'b' to go back, 'q' to quit: "
                        sys.stdout.flush()
                        raw = input(color(prompt, Color.BOLD))
                    except EOFError:
                        return 0
                    raw = (raw or "").strip()
                    if raw.lower() == "q":
                        # Quit entirely
                        return 0
                    if raw.lower() == "b":
                        # Back to results list
                        break
                    # Single selection only
                    if "," in raw or "-" in raw:
                        print(color("Please select a single index only.", Color.YELLOW))
                        continue
                    try:
                        one_idx = int(raw)
                    except ValueError:
                        print(color("Invalid selection.", Color.YELLOW))
                        continue
                    if not (1 <= one_idx <= len(files_list)):
                        print(color("Selection out of range.", Color.YELLOW))
                        continue
                    sel_file = files_list[one_idx - 1]
                    finfo = build_file_info(
                        details,
                        sel_file,
                        hash_type=args.hash,
                        human=not args.no_human,
                        download_dir=args.download_dir,
                    )
                    # Show a details view and action menu
                    print_file_details(finfo)
                    try:
                        action = (
                            input(
                                color(
                                    "Action: [d]ownload, find [h]ash, [o]pen URL, [c]opy URL, [b]ack, [q]uit: ",
                                    Color.BOLD,
                                )
                            )
                            .strip()
                            .lower()
                        )
                    except EOFError:
                        return 0
                    if action in ("b", ""):
                        # back to file list view
                        continue
                    if action == "q":
                        return 0
                    if action == "o":
                        import webbrowser

                        url = finfo.get("url")
                        if url:
                            webbrowser.open(url)
                            print(color("Opened URL in browser.", Color.DIM))
                        else:
                            print(color("No URL to open.", Color.YELLOW))
                        continue
                    if action == "c":
                        try:
                            import subprocess as _sp

                            url = finfo.get("url") or ""
                            if not url:
                                print(color("No URL to copy.", Color.YELLOW))
                            else:
                                # Prefer Wayland-native wl-copy, then fall back
                                if shutil.which("wl-copy"):
                                    _sp.run(
                                        ["wl-copy"], input=url.encode(), check=False
                                    )
                                    print(
                                        color(
                                            "Copied URL to clipboard (wl-copy).",
                                            Color.DIM,
                                        )
                                    )
                                elif shutil.which("xclip"):
                                    _sp.run(
                                        ["xclip", "-selection", "clipboard"],
                                        input=url.encode(),
                                        check=False,
                                    )
                                    print(
                                        color(
                                            "Copied URL to clipboard (xclip).",
                                            Color.DIM,
                                        )
                                    )
                                elif shutil.which("xsel"):
                                    _sp.run(
                                        ["xsel", "--clipboard", "--input"],
                                        input=url.encode(),
                                        check=False,
                                    )
                                    print(
                                        color(
                                            "Copied URL to clipboard (xsel).", Color.DIM
                                        )
                                    )
                                elif shutil.which("pbcopy"):
                                    _sp.run(["pbcopy"], input=url.encode(), check=False)
                                    print(
                                        color(
                                            "Copied URL to clipboard (pbcopy).",
                                            Color.DIM,
                                        )
                                    )
                                elif os.name == "nt":
                                    _sp.run(["clip"], input=url.encode(), check=False)
                                    print(
                                        color(
                                            "Copied URL to clipboard (clip).", Color.DIM
                                        )
                                    )
                                else:
                                    print(
                                        color(
                                            "No clipboard utility found (try wl-clipboard).",
                                            Color.YELLOW,
                                        )
                                    )
                        except Exception:
                            print(color("Failed to copy to clipboard.", Color.YELLOW))
                        continue
                    if action == "h":
                        print("\n")
                        sha1 = finfo.get("sha1")
                        if not sha1:
                            print(
                                color(
                                    "No SHA1 available for this file.",
                                    Color.YELLOW | Color.BOLD
                                    if hasattr(Color, "BOLD")
                                    else Color.YELLOW,
                                )
                            )
                            time.sleep(3)
                            continue
                        res = search_sha1_rg_adguard(sha1, debug=args.verbose > 0)
                        if not res:
                            print(color("No file found on rg-adguard.", Color.YELLOW))
                            time.sleep(3)
                        else:
                            name, link = res
                            print(color("Found on rg-adguard:", Color.YELLOW))
                            print(f"Name: {name}")
                            print(f"Link: {link}")
                            time.sleep(3)
                        continue
                    url = finfo.get("url")
                    if action != "d":
                        print(color("Unknown action.", Color.YELLOW))
                        continue
                    if not url:
                        print(color("Could not build file URL.", Color.YELLOW))
                        continue
                    if args.dry_run:
                        print(color("Dry run: skipping download.", Color.DIM))
                        continue
                    # Try aria2 unless disabled
                    # Ensure download directory exists just-in-time
                    try:
                        os.makedirs(args.download_dir, exist_ok=True)
                    except Exception as e:
                        print(
                            color(
                                f"Could not create download dir '{args.download_dir}': {e}",
                                Color.YELLOW,
                            ),
                            file=sys.stderr,
                        )
                        continue
                    if not args.no_aria2:
                        aria2_path = args.aria2_path or shutil.which("aria2c")
                        if not aria2_path:
                            print(
                                color(
                                    "aria2 not found or disabled. Using PySmartDL fallback.",
                                    Color.YELLOW,
                                )
                            )
                        else:
                            print(color("Found aria2", Color.GREEN))
                            cmd = [
                                aria2_path,
                                "--continue=true",
                                f"--max-connection-per-server={args.max_connections}",
                                f"--split={args.max_connections}",
                                f"--dir={args.download_dir}",
                            ]
                            if not args.verbose:
                                cmd += ["--console-log-level=error"]
                            cmd.append(url)
                            if args.verbose:
                                print(
                                    color("Running aria2c:", Color.MAGENTA),
                                    " ".join(cmd),
                                )
                            # Run aria2 and wait; let it print directly to terminal
                            ret = subprocess.call(cmd)
                            if ret == 0:
                                print(color("Download finished.", Color.GREEN))
                            else:
                                print(
                                    color(f"aria2 exited with code {ret}", Color.YELLOW)
                                )
                            # Return to the file list loop either way
                            continue
                    # Fallback: PySmartDL
                    if args.no_aria2:
                        print(
                            color(
                                "aria2 not found or disabled. Using PySmartDL fallback.",
                                Color.YELLOW,
                            )
                        )
                    try:
                        from pySmartDL import SmartDL  # type: ignore
                    except Exception:
                        print(
                            color(
                                "PySmartDL not installed; please install or use aria2.",
                                Color.YELLOW,
                            )
                        )
                        # back to file list in this item loop
                        continue
                    # PySmartDL single file
                    print(color(f"Downloading: {url}", Color.MAGENTA))
                    obj = SmartDL(url, dest=args.download_dir)
                    obj.start(blocking=False)
                    while not obj.isFinished():
                        time.sleep(0.2)
                    if obj.isSuccessful():
                        print(color("Download finished.", Color.GREEN))
                    elif obj.get_errors():
                        print(color("Failed", Color.YELLOW))
                    # Continue to show the file list again regardless
                    continue
    else:
        print(table)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

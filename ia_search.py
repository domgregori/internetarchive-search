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
import signal
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

from contextlib import contextmanager
import io
from subprocess import Popen, DEVNULL

@contextmanager
def _silence_stdio():
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        yield
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err


def open_url_quiet(url: str) -> bool:
    """Open a URL using platform tools while suppressing console noise."""
    try:
        if sys.platform.startswith("linux"):
            if shutil.which("xdg-open"):
                Popen(["xdg-open", url], stdout=DEVNULL, stderr=DEVNULL)
                return True
            if shutil.which("gio"):
                Popen(["gio", "open", url], stdout=DEVNULL, stderr=DEVNULL)
                return True
        elif sys.platform == "darwin":
            Popen(["open", url], stdout=DEVNULL, stderr=DEVNULL)
            return True
        elif os.name == "nt":
            try:
                os.startfile(url)  # type: ignore[attr-defined]
                return True
            except Exception:
                Popen(["cmd", "/c", "start", "", url], stdout=DEVNULL, stderr=DEVNULL, shell=True)
                return True
        # Fallback to webbrowser with silenced stdio
        with _silence_stdio():
            import webbrowser
            webbrowser.open(url)
        return True
    except Exception:
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard using common utilities.
    Returns True on success, False otherwise. Prints user feedback.
    """
    try:
        import subprocess as _sp
        if shutil.which("wl-copy"):
            _sp.run(["wl-copy"], input=text.encode(), check=False)
            print(color("Copied to clipboard (wl-copy).", Color.YELLOW))
            time.sleep(2)
            return True
        if shutil.which("xclip"):
            _sp.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=False)
            print(color("Copied to clipboard (xclip).", Color.YELLOW))
            time.sleep(2)
            return True
        if shutil.which("xsel"):
            _sp.run(["xsel", "--clipboard", "--input"], input=text.encode(), check=False)
            print(color("Copied to clipboard (xsel).", Color.YELLOW))
            time.sleep(2)
            return True
        if shutil.which("pbcopy"):
            _sp.run(["pbcopy"], input=text.encode(), check=False)
            print(color("Copied to clipboard (pbcopy).", Color.YELLOW))
            time.sleep(2)
            return True
        if os.name == "nt":
            _sp.run(["clip"], input=text.encode(), check=False)
            print(color("Copied to clipboard (clip).", Color.YELLOW))
            time.sleep(2)
            return True
        print(color("No clipboard utility found (try wl-clipboard).", Color.YELLOW))
        time.sleep(2)
        return False
    except Exception:
        print(color("Failed to copy to clipboard.", Color.YELLOW))
        time.sleep(2)
        return False


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


DEFAULT_FIELDS = [
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
]


def list_fields() -> str:
    lines = [color("Common field options (curated):", Color.BOLD)]
    for f in DEFAULT_FIELDS:
        lines.append(f"  - {f}")
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
        # Create item and attach commonly used extra fields
        it = Item(identifier=str(identifier), downloads=downloads, title=title)
        # Prefer explicit date, fallback to publicdate if provided
        it.date = d.get("date") or d.get("publicdate")
        items.append(it)
    return items


_NEEDS_REDRAW = False


def _on_resize(signum, frame):  # pragma: no cover
    global _NEEDS_REDRAW
    _NEEDS_REDRAW = True


def format_table(items: List[Item], long_columns: bool = False, terminal_aware: bool = True) -> str:
    if not items:
        return color("No results.", Color.YELLOW)

    # determine widths
    id_width = max(10, *(len(i.identifier) for i in items))
    date_width = 10  # YYYY-MM-DD
    wrap_w = 50
    if long_columns:
        title_width = max(5, *(len(i.title or "") for i in items))
    else:
        # terminal-aware allocation to title if enabled
        if terminal_aware:
            term_cols = shutil.get_terminal_size(fallback=(120, 24)).columns
            # gaps: between 5 columns -> 4 gaps of two spaces = 8
            dl_values = [i.downloads for i in items if i.downloads is not None]
            dl_width = max(9, len(str(max(dl_values))) if dl_values else 9)
            fixed = 3 + id_width + dl_width + date_width + 8
            avail = max(10, term_cols - fixed)
            # Apply a reasonable max to avoid overly wide columns
            MAX_TITLE = 120
            title_width = min(avail, MAX_TITLE)
        else:
            title_width = wrap_w
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
        + "  "
        + color("DATE".ljust(date_width), Color.BOLD)
    )
    sep = "-" * (3 + id_width + dl_width + title_width + date_width + 8)

    lines = [header, sep]
    for idx, it in enumerate(items, 1):
        full_title = (it.title or "").replace("\n", " ")
        if long_columns:
            chunks = [full_title]
        else:
            width = title_width if terminal_aware else wrap_w
            chunks = [full_title[x : x + width] for x in range(0, len(full_title), width)] or [""]
        dl = "-" if it.downloads is None else str(it.downloads)
        date_raw = getattr(it, "date", None) or ""
        date_s = (str(date_raw)[:10]) if date_raw else "-"
        idxs = color(str(idx).rjust(3), Color.MAGENTA)
        ident = color(it.identifier.ljust(id_width), Color.BLUE)
        dlc = color(dl.rjust(dl_width), Color.GREEN)
        datec = color(date_s.ljust(date_width), Color.DIM)
        for j, chunk in enumerate(chunks):
            titlec = color(chunk.ljust(title_width), Color.DIM)
            if j == 0:
                lines.append(f"{idxs}  {ident}  {dlc}  {titlec}  {datec}")
            else:
                blank_idx = " " * 3
                blank_ident = " " * id_width
                blank_dl = " " * dl_width
                lines.append(f"{blank_idx}  {blank_ident}  {blank_dl}  {titlec}  {' ' * date_width}")
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
    long_columns: bool = False,
    terminal_aware: bool = True,
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
    # terminal-aware name column unless disabled
    if long_columns:
        name_w = max(len(f.get("name", "")) for f in files) if files else wrap_w
    elif terminal_aware:
        term_cols = shutil.get_terminal_size(fallback=(120, 24)).columns
        gaps = 6
        size_w = 12
        hash_label = hash_type.upper()
        hash_w = max(8, len(hash_label), 40)
        fixed = idx_w + size_w + hash_w + gaps
        avail = max(10, term_cols - fixed)
        MAX_NAME = 140
        name_w = min(avail, MAX_NAME)
    else:
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
        # Wrap the filename into chunks based on chosen width unless long_columns
        if long_columns:
            chunks = [name]
        else:
            width = name_w if terminal_aware else wrap_w
            chunks = [name[x : x + width] for x in range(0, len(name), width)] or [""]
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
        "--list-sort-options",
        action="store_true",
        help="List curated supported sort options and exit",
    )
    p.add_argument(
        "--list-field-options",
        action="store_true",
        help="List curated field options and exit",
    )
    p.add_argument(
        "--long-columns",
        action="store_true",
        help="Disable truncation/wrapping in results and files tables",
    )
    p.add_argument(
        "--no-terminal-aware",
        action="store_true",
        help="Disable terminal-width aware column sizing (use fixed widths)",
    )
    p.add_argument(
        "--fields",
        nargs="*",
        default=DEFAULT_FIELDS,
        help=(
            "Fields to request; defaults to a curated set (see --list-field-options)"
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
    # Setup terminal resize handler to trigger redraws
    try:
        signal.signal(signal.SIGWINCH, _on_resize)
    except Exception:
        pass
    # If requested, print lists and exit
    if getattr(args, 'list_sort_options', False):
        print(list_sorts())
        return 0
    if getattr(args, 'list_field_options', False):
        print(list_fields())
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
            color("Error: --query is required unless using --list-sort-options", Color.YELLOW),
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
    results_filter = None  # persistent results filter across paging
    table = format_table(items, getattr(args, 'long_columns', False), terminal_aware=not getattr(args, 'no_terminal_aware', False))
    if items:
        while True:
            # print formatted results table with headers (clear if resized)
            if _NEEDS_REDRAW:
                print("\033[2J\033[H", end="")
                globals()['_NEEDS_REDRAW'] = False
            print(
                format_table(
                    items,
                    getattr(args, 'long_columns', False),
                    terminal_aware=not getattr(args, 'no_terminal_aware', False),
                )
            )
            print()  # spacer above footer
            print(color(f"( Page: {args.page}  [n]ext  [p]rev  [/] filter  [r]eset  [s]earch  [q]uit )", Color.DIM))
            # unified prompt label; footer lists actions
            print(color("", Color.DIM), end="")
            sel = None
            try:
                # show active results filter in prompt if set
                prompt = (
                    f"Selection or Action (filter='{results_filter}'): "
                    if results_filter else "Selection or Action: "
                )
                raw = input(color(prompt, Color.BOLD)).strip()
            except EOFError:
                raw = ""
            if not raw:
                sel = None
            elif raw.lower() in {"q", "n", "p", "r", "s"}:
                sel = raw  # handled downstream
            elif raw.startswith("/"):
                sel = "/"
            else:
                try:
                    idx = int(raw)
                    if 1 <= idx <= len(items):
                        sel = idx - 1
                    else:
                        sel = None
                except ValueError:
                    print(color("Invalid input.", Color.YELLOW))
                    sel = None
            if sel == "/":
                # set runtime results filter (by identifier/title substring)
                try:
                    # allow immediate term after '/', e.g., '/foo'
                    term = raw[1:] if len(raw) > 1 else input(color("Filter text: ", Color.BOLD)).strip()
                except EOFError:
                    term = ""
                results_filter = term or None
                # apply filter to current items
                base_items = parse_items(payload)
                if results_filter:
                    lf = results_filter.lower()
                    items = [it for it in base_items if lf in (it.identifier.lower() + " " + (it.title or "").lower())]
                else:
                    items = base_items
                continue
            if isinstance(sel, str) and sel == 's':
                # start a new search query interactively
                try:
                    new_q = input(color("New query (blank to cancel): ", Color.BOLD)).strip()
                except EOFError:
                    new_q = ""
                if not new_q:
                    # no change
                    continue
                args.query = new_q
                args.page = 1
                results_filter = None
                # rebuild description terms only if originally provided; include --iso only if set
                desc_terms = []
                if getattr(args, 'iso', False):
                    desc_terms.extend(["iso", "cd-rom"])
                if getattr(args, 'description_terms', None):
                    desc_terms.extend(args.description_terms)
                try:
                    url = build_url(
                        args.query,
                        args.mediatype,
                        args.rows,
                        args.page,
                        args.sort,
                        args.fields,
                        description_terms=(desc_terms or None),
                    )
                    payload = fetch_json(url, debug=args.verbose > 0)
                    items = parse_items(payload)
                    sel = None
                    continue
                except Exception as e:
                    print(color(f"Search failed: {e}", Color.YELLOW))
                    sel = None
                    continue
            if isinstance(sel, str) and sel == 'r':
                # reset results filter and return to first page
                results_filter = None
                args.page = 1
                try:
                    url = build_url(
                        args.query,
                        args.mediatype,
                        args.rows,
                        args.page,
                        args.sort,
                        args.fields,
                        description_terms=(desc_terms or None),
                    )
                    payload = fetch_json(url, debug=args.verbose > 0)
                    items = parse_items(payload)
                except Exception as e:
                    print(color(f"Failed to reload page 1: {e}", Color.YELLOW))
                    items = parse_items(payload)
                continue
            if isinstance(sel, str) and sel == 'r':
                # reset results filter
                results_filter = None
                items = parse_items(payload)
                continue
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
                    base_items = parse_items(payload)
                    if results_filter:
                        lf = results_filter.lower()
                        items = [it for it in base_items if lf in (it.identifier.lower() + " " + (it.title or "").lower())]
                    else:
                        items = base_items
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
                    base_items = parse_items(payload)
                    if results_filter:
                        lf = results_filter.lower()
                        items = [it for it in base_items if lf in (it.identifier.lower() + " " + (it.title or "").lower())]
                    else:
                        items = base_items
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
            # Item-scoped interactive files loop
            while True:
                    # Print only the single colorful files table
                    # Build file list for selection
                    files_obj = details.get("files", {})
                    if isinstance(files_obj, dict):
                        files_list_all = [
                            {"name": k.lstrip("/"), **(v or {})}
                            for k, v in files_obj.items()
                        ]
                    else:
                        files_list_all = files_obj or []
                    # apply ext and contains filters before paging
                    files_list = files_list_all
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
                    # Apply runtime files_filter if set (after args-based filters, before paging)
                    if 'files_filter' in locals() and files_filter:
                        sub = files_filter.lower()
                        files_list = [
                            f for f in files_list if sub in f.get("name", "").lower()
                        ]
                    if not files_list:
                        print(color("No files match filters.", Color.YELLOW))
                        break

                    # Files pagination using rows as page size
                    if 'files_page' not in locals():
                        files_page = 1
                    page_size = max(1, args.rows)
                    total_pages = max(1, (len(files_list) + page_size - 1) // page_size)
                    if files_page > total_pages:
                        files_page = total_pages
                    start = (files_page - 1) * page_size
                    end = start + page_size
                    page_slice = files_list[start:end]

                    if _NEEDS_REDRAW:
                        print("\033[2J\033[H", end="")
                        globals()['_NEEDS_REDRAW'] = False
                    print(
                        format_item_details(
                            {**details, "files": page_slice},
                            ext_filter=None,  # already filtered
                            human=not args.no_human,
                            hash_type=args.hash,
                            long_columns=getattr(args, 'long_columns', False),
                            terminal_aware=not getattr(args, 'no_terminal_aware', False),
                        )
                    )
                    print()  # spacer above footer
                    footer = f"( Page: {files_page}/{total_pages}  [n]ext  [p]rev  [/] filter  [r]eset  [b]ack  [q]uit  [c]opy page  [o]pen page )"
                    print(color(footer, Color.DIM))
                    try:
                        sys.stdout.flush()
                        # Include active filter in prompt label, if any
                        if 'files_filter' in locals() and files_filter:
                            prompt = f"Selection or Action (filter='{files_filter}'): "
                        else:
                            prompt = "Selection or Action: "
                        raw = input(color(prompt, Color.BOLD))
                    except EOFError:
                        return 0
                    raw = (raw or "").strip()
                    if raw.lower() == "q":
                        # Quit entirely
                        return 0
                    if raw.startswith("/"):
                        # Set runtime filter; allow inline "/foo" or prompt if just "/"
                        try:
                            term = raw[1:] if len(raw) > 1 else input(color("Filter text: ", Color.BOLD)).strip()
                        except EOFError:
                            term = ""
                        files_filter = term or None
                        files_page = 1
                        continue
                    if raw.lower() == "r":
                        files_filter = None
                        files_page = 1
                        continue
                    if raw.lower() == "b":
                        # Back to results list
                        break
                    if raw.lower() == 'c':
                        ident = _first(details.get("metadata", {}), "identifier")
                        page_url = f"https://archive.org/details/{ident}" if ident else ""
                        if not page_url:
                            print(color("No page URL available.", Color.YELLOW))
                        else:
                            copy_to_clipboard(page_url)
                        continue
                    if raw.lower() == 'o':
                        ident = _first(details.get("metadata", {}), "identifier")
                        page_url = f"https://archive.org/details/{ident}" if ident else ""
                        if not page_url:
                            print(color("No page URL available.", Color.YELLOW))
                        else:
                            if open_url_quiet(page_url):
                                print(color("Opened page in browser.", Color.DIM))
                            else:
                                print(color("Failed to open page URL.", Color.YELLOW))
                        continue
                    if raw.lower() == 'n':
                        files_page = min(total_pages, files_page + 1)
                        continue
                    if raw.lower() == 'p':
                        files_page = max(1, files_page - 1)
                        continue
                    # Single selection only
                    if "," in raw or "-" in raw:
                        print(color("Please select a single index only.", Color.YELLOW))
                        continue
                    try:
                        one_idx = int(raw)
                    except ValueError:
                        print(color("Invalid selection.", Color.YELLOW))
                        continue
                    if not (1 <= one_idx <= len(page_slice)):
                        print(color("Selection out of range.", Color.YELLOW))
                        continue
                    sel_file = page_slice[one_idx - 1]
                    finfo = build_file_info(
                        details,
                        sel_file,
                        hash_type=args.hash,
                        human=not args.no_human,
                        download_dir=args.download_dir,
                    )
                    # Show a details view and action menu
                    print_file_details(finfo)
                    # Footer-style action hints (bracketed keys)
                    print()  # spacer above footer
                    print(color("( [d]ownload  [h]ash search  [o]pen  [c]opy  [b]ack  [q]uit )", Color.DIM))
                    try:
                        action = input(color("Selection or Action: ", Color.BOLD)).strip().lower()
                    except EOFError:
                        return 0
                    if action in ("b", ""):
                        # back to file list view
                        continue
                    if action == "q":
                        return 0
                    if action == "o":
                        dl_url = finfo.get("url")
                        if dl_url:
                            if open_url_quiet(dl_url):
                                print(color("Opened Download URL in browser.", Color.DIM))
                            else:
                                print(color("Failed to open Download URL.", Color.YELLOW))
                        else:
                            print(color("No Download URL to open.", Color.YELLOW))
                        continue
                    if action == "c":
                        # Copy the Download URL from file info
                        dl_url = finfo.get("url") or ""
                        if not dl_url:
                            print(color("No Download URL to copy.", Color.YELLOW))
                        else:
                            copy_to_clipboard(dl_url)
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

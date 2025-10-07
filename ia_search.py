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
from dataclasses import dataclass
from typing import List, Optional

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


@dataclass
class Item:
    identifier: str
    downloads: Optional[int] = None
    title: Optional[str] = None


def build_url(q: str, mediatype: Optional[str], rows: int, page: int, sort: Optional[str], fields: List[str]) -> str:
    base = "https://archive.org/advancedsearch.php"
    # Build query
    q_parts = [f"({q})"]
    if mediatype:
        q_parts.append(f"mediatype:({mediatype})")
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


def fetch_json(url: str) -> dict:
    if requests is not None:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    # urllib fallback
    with urllib.request.urlopen(url, timeout=20) as r:  # nosec B310 (fixed host)
        data = r.read()
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

    # header
    header = (
        color("IDENTIFIER".ljust(id_width), Color.BOLD)
        + "  "
        + color("DOWNLOADS".rjust(dl_width), Color.BOLD)
        + "  "
        + color("TITLE".ljust(title_width), Color.BOLD)
    )
    sep = "-" * (id_width + dl_width + title_width + 4)

    lines = [header, sep]
    for it in items:
        title = (it.title or "").replace("\n", " ")
        if len(title) > title_width:
            title = title[: title_width - 1] + "…"
        dl = "-" if it.downloads is None else str(it.downloads)
        ident = color(it.identifier.ljust(id_width), Color.BLUE)
        dlc = color(dl.rjust(dl_width), Color.GREEN)
        titlec = color(title.ljust(title_width), Color.DIM)
        lines.append(f"{ident}  {dlc}  {titlec}")
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
    p.add_argument("-q", "--query", required=True, help="Search query for 'q' (e.g., Ubuntu 22.04 iso)")
    p.add_argument("--mediatype", default=None, help="Restrict mediatype, e.g. software, audio, movies")
    p.add_argument("--rows", type=int, default=50, help="Rows per page (default: 50)")
    p.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    p.add_argument(
        "--sort",
        default="downloads desc",
        help="Sort expression (e.g., 'downloads desc', 'date desc')",
    )
    p.add_argument(
        "--fields",
        nargs="*",
        default=["identifier", "downloads", "title"],
        help="Fields to request (default: identifier downloads title)",
    )
    p.add_argument("--print-url", action="store_true", help="Print the generated URL before results")

    args = p.parse_args(argv)

    url = build_url(args.query, args.mediatype, args.rows, args.page, args.sort, args.fields)
    if args.print_url:
        print(color("Request URL:", Color.MAGENTA), url)

    try:
        payload = fetch_json(url)
    except Exception as e:
        print(color(f"Request failed: {e}", Color.YELLOW), file=sys.stderr)
        return 2

    items = parse_items(payload)
    table = format_table(items)
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


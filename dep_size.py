#!/usr/bin/env python3
"""dep-size — audit installed Python packages by on-disk size.

Reads distribution metadata (RECORD) from site-packages, sums the real
bytes per package, and prints the biggest first as a human table
(or JSON with --json). Zero dependencies, standard library only.
"""

import argparse
import glob
import importlib.metadata
import json
import os
import re
import site
import sys

__version__ = "1.0.0"

SIZE_UNITS = {"B": 1, "K": 1024, "KB": 1024, "M": 1024 ** 2, "MB": 1024 ** 2,
              "G": 1024 ** 3, "GB": 1024 ** 3}
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]{0,2})\s*$")


def parse_size(text):
    """Parse a human size like '500K', '1.5M', '1024' into bytes.

    Raises ValueError on bad input. Bare numbers are bytes.
    """
    m = _SIZE_RE.match(text)
    if not m:
        raise ValueError(f"invalid size: {text!r}")
    number, unit = float(m.group(1)), m.group(2).upper()
    if unit and unit not in SIZE_UNITS:
        raise ValueError(f"invalid size unit: {unit!r} in {text!r}")
    return int(number * SIZE_UNITS.get(unit, 1))


def format_size(nbytes):
    """Format bytes as a short human string, e.g. 1536 -> '1.5 KB'."""
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value = nbytes / 1024.0
        if value < 1024 or unit == "TB":
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
        nbytes = int(value)
    return f"{nbytes} B"  # unreachable, keeps linters quiet


def _walk_size(root):
    """Sum file sizes under root, following no symlinks to files outside."""
    total, count = 0, 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if os.path.isfile(path) and not os.path.islink(path):
                    total += os.path.getsize(path)
                    count += 1
            except OSError:
                continue
    return total, count


def measure_distribution(dist, site_dir):
    """Return (bytes, file_count) for one distribution.

    Primary source is the RECORD file (dist.files); if it lists nothing
    usable, fall back to walking the package directory and .dist-info dir.
    """
    total, count = 0, 0
    files = dist.files or []
    for rel in files:
        try:
            path = dist.locate_file(rel)
        except (OSError, ValueError):
            continue
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
                count += 1
        except OSError:
            continue
    if count:
        return total, count
    # Fallback: RECORD missing or empty — walk likely directories.
    name = re.sub(r"[-_.]+", "_", dist.metadata["Name"]).lower()
    candidates = [os.path.join(site_dir, name),
                  os.path.join(site_dir, name + ".dist-info")]
    for cand in candidates:
        if os.path.isdir(cand):
            sub_total, sub_count = _walk_size(cand)
            total += sub_total
            count += sub_count
    return total, count


def scan_site_packages(site_dirs):
    """Return a list of package dicts for the given site-packages dirs."""
    rows = []
    seen = set()
    for site_dir in site_dirs:
        try:
            dists = list(importlib.metadata.distributions(path=[site_dir]))
        except (OSError, ValueError):
            continue
        for dist in dists:
            name = dist.metadata["Name"]
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            size, files = measure_distribution(dist, site_dir)
            rows.append({
                "name": name,
                "version": dist.version or "?",
                "size_bytes": size,
                "files": files,
                "location": site_dir,
            })
    return rows


def default_site_packages():
    """All site-packages dirs importlib.metadata can see."""
    dirs = []
    for getter in (site.getsitepackages, site.getusersitepackages):
        try:
            result = getter()
        except (AttributeError, OSError):
            continue
        if isinstance(result, str):
            result = [result]
        dirs.extend(d for d in result if os.path.isdir(d))
    return sorted(set(dirs))


def resolve_venv(venv_dir):
    """Find the site-packages dir inside a virtualenv."""
    if not os.path.isdir(venv_dir):
        raise ValueError(f"venv not found: {venv_dir}")
    matches = sorted(glob.glob(os.path.join(venv_dir, "lib", "python*",
                                            "site-packages")))
    matches += sorted(glob.glob(os.path.join(venv_dir, "Lib",
                                             "site-packages")))
    for match in matches:
        if os.path.isdir(match):
            return match
    raise ValueError(f"no site-packages inside venv: {venv_dir}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="dep-size",
        description="Audit installed Python packages by on-disk size "
                    "(largest first). Human table by default, --json for machines.",
        epilog="Examples:\n"
               "  dep-size\n"
               "  dep-size --venv ./venv --top 10\n"
               "  dep-size --path /usr/lib/python3/dist-packages --json\n"
               "  dep-size --min-size 1M --sort name",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version",
                   version=f"dep-size {__version__}")
    p.add_argument("--path", action="append", default=[], metavar="DIR",
                   help="site-packages dir to scan (repeatable; default: "
                        "all site-packages on this Python)")
    p.add_argument("--venv", metavar="DIR",
                   help="scan the site-packages inside this virtualenv")
    p.add_argument("--top", type=int, default=0, metavar="N",
                   help="show only the N largest packages (0 = all)")
    p.add_argument("--min-size", default="0", metavar="SIZE",
                   help="hide packages smaller than SIZE, e.g. 500K, 1M, 2G "
                        "(default: 0)")
    p.add_argument("--sort", choices=["size", "name"], default="size",
                   help="sort by size (default) or name")
    p.add_argument("--json", action="store_true",
                   help="print machine-readable JSON instead of the table")
    p.add_argument("--no-color", action="store_true",
                   help="disable colored output (also honors NO_COLOR)")
    return p


def render_table(rows, total_bytes, use_color):
    """Render the human table. Rows already sorted and filtered."""
    def bold(text):
        return f"\033[1m{text}\033[0m" if use_color else text

    headers = ["NAME", "VERSION", "SIZE", "FILES", "SHARE"]
    data = []
    for r in rows:
        share = (r["size_bytes"] / total_bytes * 100) if total_bytes else 0.0
        data.append([r["name"], r["version"], format_size(r["size_bytes"]),
                     str(r["files"]), f"{share:.1f}%"])
    widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    total_row = ["TOTAL", "", format_size(total_bytes),
                 str(sum(r["files"] for r in rows)), "100%"]
    for i, cell in enumerate(total_row):
        widths[i] = max(widths[i], len(cell))

    def fmt(row):
        cells = [row[0].ljust(widths[0]), row[1].ljust(widths[1]),
                 row[2].rjust(widths[2]), row[3].rjust(widths[3]),
                 row[4].rjust(widths[4])]
        return "  ".join(cells)

    lines = [bold(fmt(headers))]
    lines.extend(fmt(row) for row in data)
    lines.append(bold(fmt(total_row)))
    return "\n".join(lines) + "\n"


def render_json(rows, total_bytes, site_dirs):
    """Render the machine-readable JSON document."""
    out = {
        "total_bytes": total_bytes,
        "total_human": format_size(total_bytes),
        "site_packages": site_dirs,
        "packages": [{
            "name": r["name"],
            "version": r["version"],
            "size_bytes": r["size_bytes"],
            "size_human": format_size(r["size_bytes"]),
            "files": r["files"],
            "share_pct": round(r["size_bytes"] / total_bytes * 100, 1)
                         if total_bytes else 0.0,
            "location": r["location"],
        } for r in rows],
    }
    return json.dumps(out, indent=2) + "\n"


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.top < 0:
        build_parser().error("--top must be >= 0")
    try:
        min_bytes = parse_size(args.min_size)
    except ValueError as exc:
        build_parser().error(str(exc))

    site_dirs = []
    try:
        if args.venv:
            site_dirs.append(resolve_venv(args.venv))
        for path in args.path:
            if not os.path.isdir(path):
                print(f"dep-size: not a directory: {path}", file=sys.stderr)
                return 1
            site_dirs.append(path)
    except ValueError as exc:
        print(f"dep-size: {exc}", file=sys.stderr)
        return 1
    if not site_dirs:
        site_dirs = default_site_packages()
    if not site_dirs:
        print("dep-size: no site-packages directory found", file=sys.stderr)
        return 1

    rows = scan_site_packages(site_dirs)
    total = sum(r["size_bytes"] for r in rows)
    rows = [r for r in rows if r["size_bytes"] >= min_bytes]
    rows.sort(key=lambda r: r["name"].lower() if args.sort == "name"
              else -r["size_bytes"])
    if args.top:
        rows = rows[:args.top]

    use_color = (sys.stdout.isatty() and not args.no_color
                 and "NO_COLOR" not in os.environ)
    if args.json:
        sys.stdout.write(render_json(rows, total, site_dirs))
    else:
        sys.stdout.write(render_table(rows, total, use_color))
    return 0


if __name__ == "__main__":
    sys.exit(main())

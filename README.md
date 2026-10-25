# dep-size

> Audit installed Python packages by on-disk size — biggest first. Daily Tools #19.

## Why
When a virtualenv or system Python balloons to hundreds of megabytes, `pip list`
tells you versions but never sizes, and `du -sh site-packages/*` shows raw
directories without versions, file counts, or a machine-readable form. dep-size
reads distribution metadata (RECORD) and prints one honest table — name,
version, size, file count, share of total — or the same data as JSON for
scripts and CI. The closest alternative,
[jambhaleAnuj/python-package-size-analyzer](https://github.com/jambhaleAnuj/python-package-size-analyzer),
prints only a plain MB table: no `--json`, no `--top`/`--min-size` filter, no
venv targeting (`--path`/`--venv`), no share % / file count / total, and it
sizes packages by walking directories instead of reading RECORD.

## Install
```bash
git clone https://github.com/Kayzenn123/dep-size.git
cd dep-size
# no dependencies — Python standard library only
```
Requires: Python >= 3.9

## Usage
```bash
python3 dep_size.py --help
python3 dep_size.py --top 10
python3 dep_size.py --venv ./venv --top 10
python3 dep_size.py --path /usr/lib/python3/dist-packages --json
python3 dep_size.py --min-size 1M --sort name
```

| Flag | Function | Default |
| --- | --- | --- |
| `--path DIR` | site-packages dir to scan (repeatable) | all site-packages on this Python |
| `--venv DIR` | scan the site-packages inside this virtualenv | — |
| `--top N` | show only the N largest packages | 0 (all) |
| `--min-size SIZE` | hide packages smaller than SIZE, e.g. `500K`, `1M`, `2G` | 0 |
| `--sort size\|name` | sort order | `size` |
| `--json` | print machine-readable JSON instead of the table | off |
| `--no-color` | disable colored output (also honors `NO_COLOR`) | color only on a TTY |
| `--version` | print version and exit | — |

Exit codes: `0` success, `1` runtime error (e.g. path is not a directory),
`2` argument error.

## Example output
Command:
```bash
python3 dep_size.py --top 10
```
Output (real, copied from an actual run on this machine's system Python):
```text
NAME        VERSION         SIZE  FILES  SHARE
SciPy       1.11.4       76.9 MB   2055  23.4%
pandas      2.1.4+dfsg   66.6 MB   2912  20.2%
sympy       1.12         59.8 MB   2920  18.2%
numpy       1.26.4       32.8 MB   1191  10.0%
plotly      5.15.0       30.7 MB  12246   9.3%
matplotlib  3.6.3        21.5 MB    526   6.6%
pip         24.0         12.5 MB    993   3.8%
lxml        5.2.1         4.8 MB    113   1.5%
mpmath      0.0.0         4.3 MB    172   1.3%
setuptools  68.1.2        4.2 MB    347   1.3%
TOTAL                   328.7 MB  23475   100%
```

Command:
```bash
python3 dep_size.py --path examples/fake-site-packages --json
```
Output (real, copied from an actual run):
```text
{
  "total_bytes": 53760,
  "total_human": "52.5 KB",
  "site_packages": [
    "examples/fake-site-packages"
  ],
  "packages": [
    {
      "name": "demo-heavy",
      "version": "3.1",
      "size_bytes": 53248,
      "size_human": "52 KB",
      "files": 2,
      "share_pct": 99.0,
      "location": "examples/fake-site-packages"
    },
    {
      "name": "demo-light",
      "version": "0.4",
      "size_bytes": 512,
      "size_human": "512 B",
      "files": 1,
      "share_pct": 1.0,
      "location": "examples/fake-site-packages"
    }
  ]
}
```

## How it works
1. Finds site-packages dirs from `site.getsitepackages()` /
   `site.getusersitepackages()`, or the `--path` / `--venv` you point at.
2. For each distribution found by `importlib.metadata`, sums the byte sizes
   of the files listed in its RECORD file (accurate, no guessing); if RECORD
   is missing or empty, walks the package directory and `.dist-info` dir.
3. Dedupes by package name (first site-packages dir wins), filters by
   `--min-size`, sorts by size or name, caps at `--top N`, and prints the
   table (or JSON). The TOTAL row always covers all scanned packages, even
   when `--top` hides some rows.

## Limitations
- Sizes come from RECORD when present; packages installed without RECORD
  (rare, e.g. some system packages) fall back to a directory walk, which
  can miss files installed outside the package directory.
- A package installed in two scanned site-packages dirs is counted once
  (the first one found).
- Symlinked files are not followed when summing sizes.
- Only Python distributions are measured — a venv's `bin/` scripts and
  non-package data are not included.
- Debian/Ubuntu system packages sometimes report version `0.0.0` when the
  distribution metadata carries no version; the size is still correct.

## Development
```bash
python3 -m unittest discover -s test -v
```

## License
MIT

---
Ringkasan (Bahasa Indonesia): dep-size mengaudit ukuran paket Python yang
terinstall dan menampilkan yang terbesar dulu sebagai tabel (atau JSON dengan
`--json`). Bisa menarget venv atau folder site-packages apa pun, dengan
filter `--top` dan `--min-size`. Batasannya: ukuran diambil dari RECORD
distribusi, paket tanpa RECORD dihitung lewat jalan direktori, dan paket yang
terinstall di dua lokasi hanya dihitung sekali.

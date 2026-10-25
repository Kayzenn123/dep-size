#!/usr/bin/env python3
"""Tests for dep-size. Fixtures are synthetic fake site-packages dirs."""
import importlib.metadata
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dep_size


def make_dist(site_dir, name, version, files, record=True):
    """Create a fake distribution.

    files: {relative_path: size_in_bytes}. When record=True a RECORD file
    lists them; otherwise only METADATA exists (walk fallback case).
    """
    dist_info = os.path.join(site_dir, f"{name}-{version}.dist-info")
    os.makedirs(dist_info, exist_ok=True)
    with open(os.path.join(dist_info, "METADATA"), "w") as f:
        f.write(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    lines = []
    for rel, size in files.items():
        path = os.path.join(site_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        if record:
            lines.append(f"{rel},, {size}".replace(" ", ""))
    if record:
        lines.append("RECORD,,")
        with open(os.path.join(dist_info, "RECORD"), "w") as f:
            f.write("\n".join(lines) + "\n")
    return dist_info


class FixtureMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = os.path.join(self.tmp.name, "site-packages")
        os.makedirs(self.site)
        make_dist(self.site, "FakeBig", "2.0",
                  {"fakebig/__init__.py": 1000, "fakebig/data.bin": 9000})
        make_dist(self.site, "FakeSmall", "0.1",
                  {"fakesmall/__init__.py": 100})
        make_dist(self.site, "NoRecord", "1.0",
                  {"norecord/__init__.py": 500}, record=False)

    def tearDown(self):
        self.tmp.cleanup()


class TestFormatParse(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(dep_size.format_size(0), "0 B")
        self.assertEqual(dep_size.format_size(512), "512 B")
        self.assertEqual(dep_size.format_size(1024), "1 KB")
        self.assertEqual(dep_size.format_size(1536), "1.5 KB")
        self.assertEqual(dep_size.format_size(2 * 1024 * 1024), "2 MB")

    def test_parse_size(self):
        self.assertEqual(dep_size.parse_size("1024"), 1024)
        self.assertEqual(dep_size.parse_size("500K"), 500 * 1024)
        self.assertEqual(dep_size.parse_size("1.5M"), int(1.5 * 1024 ** 2))
        self.assertEqual(dep_size.parse_size("2G"), 2 * 1024 ** 3)
        with self.assertRaises(ValueError):
            dep_size.parse_size("abc")
        with self.assertRaises(ValueError):
            dep_size.parse_size("10Z")


class TestMeasure(FixtureMixin):
    def test_measure_from_record(self):
        dist = next(d for d in
                    importlib.metadata.distributions(path=[self.site])
                    if d.metadata["Name"] == "FakeBig")
        size, count = dep_size.measure_distribution(dist, self.site)
        self.assertEqual((size, count), (10000, 2))

    def test_measure_fallback_without_record(self):
        dist = next(d for d in
                    importlib.metadata.distributions(path=[self.site])
                    if d.metadata["Name"] == "NoRecord")
        size, count = dep_size.measure_distribution(dist, self.site)
        self.assertEqual((size, count), (500, 1))

    def test_scan_finds_all(self):
        rows = dep_size.scan_site_packages([self.site])
        names = sorted(r["name"] for r in rows)
        self.assertEqual(names, ["FakeBig", "FakeSmall", "NoRecord"])
        big = next(r for r in rows if r["name"] == "FakeBig")
        self.assertEqual(big["size_bytes"], 10000)
        self.assertEqual(big["version"], "2.0")

    def test_scan_dedupes_across_dirs(self):
        other = os.path.join(self.tmp.name, "other-site")
        os.makedirs(other)
        make_dist(other, "FakeBig", "9.9", {"fakebig/__init__.py": 1})
        rows = dep_size.scan_site_packages([self.site, other])
        bigs = [r for r in rows if r["name"] == "FakeBig"]
        self.assertEqual(len(bigs), 1)


class TestRender(FixtureMixin):
    def test_table_contains_rows_and_total(self):
        rows = dep_size.scan_site_packages([self.site])
        rows.sort(key=lambda r: -r["size_bytes"])
        total = sum(r["size_bytes"] for r in rows)
        out = dep_size.render_table(rows, total, use_color=False)
        self.assertIn("FakeBig", out)
        self.assertIn("TOTAL", out)
        self.assertIn("10.4 KB", out)  # 10600 bytes total
        self.assertNotIn("\x1b[", out)

    def test_json_parseable(self):
        rows = dep_size.scan_site_packages([self.site])
        rows.sort(key=lambda r: -r["size_bytes"])
        total = sum(r["size_bytes"] for r in rows)
        doc = json.loads(dep_size.render_json(rows, total, [self.site]))
        self.assertEqual(doc["total_bytes"], 10600)
        self.assertEqual(doc["site_packages"], [self.site])
        self.assertEqual(doc["packages"][0]["name"], "FakeBig")


class TestCLI(FixtureMixin):
    def run_main(self, args, env_extra=None):
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env.update(env_extra or {})
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            old_env = dict(os.environ)
            os.environ.clear()
            os.environ.update(env)
            try:
                code = dep_size.main(args)
            finally:
                os.environ.clear()
                os.environ.update(old_env)
        return code, out.getvalue(), err.getvalue()

    def test_top_limits_rows(self):
        code, out, _ = self.run_main(["--path", self.site, "--top", "1"])
        self.assertEqual(code, 0)
        self.assertIn("FakeBig", out)
        self.assertNotIn("FakeSmall", out)

    def test_min_size_filters(self):
        code, out, _ = self.run_main(["--path", self.site,
                                      "--min-size", "1K"])
        self.assertEqual(code, 0)
        self.assertIn("FakeBig", out)
        self.assertNotIn("FakeSmall", out)

    def test_sort_by_name(self):
        code, out, _ = self.run_main(["--path", self.site, "--sort", "name"])
        self.assertEqual(code, 0)
        self.assertLess(out.index("FakeBig"), out.index("FakeSmall"))
        self.assertLess(out.index("FakeSmall"), out.index("NoRecord"))

    def test_bad_path_exit_1(self):
        code, out, err = self.run_main(["--path", "/does/not/exist"])
        self.assertEqual(code, 1)
        self.assertIn("not a directory", err)

    def test_bad_arg_exit_2(self):
        with self.assertRaises(SystemExit) as ctx:
            dep_size.main(["--sort", "bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_color_env(self):
        code, out, _ = self.run_main(["--path", self.site],
                                     env_extra={"NO_COLOR": "1"})
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b[", out)

    def test_e2e_subprocess_json(self):
        script = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "dep_size.py")
        proc = subprocess.run(
            [sys.executable, script, "--path", self.site, "--json"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["total_bytes"], 10600)
        self.assertEqual(len(doc["packages"]), 3)

    def test_e2e_version_flag(self):
        script = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "dep_size.py")
        proc = subprocess.run([sys.executable, script, "--version"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dep-size 1.0.0", proc.stdout)


if __name__ == "__main__":
    unittest.main()

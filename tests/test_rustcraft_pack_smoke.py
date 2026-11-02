"""Synthetic offline tests for RustCraft Modrinth .mrpack manifest smoke check."""
import io
import importlib.util
import json
from pathlib import Path
import zipfile
import unittest

spec = importlib.util.spec_from_file_location(
    "rustcraft_pack_smoke", Path(__file__).resolve().parents[1] / "tools" / "rustcraft_pack_smoke.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_pack(files=None, mc="1.20.1", fmt=1, metadata=None):
    buf = io.BytesIO()
    data = {
        "formatVersion": fmt, "game": "minecraft",
        "name": "Synthetic Homestead", "versionId": "2.0.1",
        "dependencies": {"minecraft": mc, "fabric-loader": "0.19.5"},
        "files": files or [],
    }
    data.update(metadata or {})
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("modrinth.index.json", json.dumps(data))
        z.writestr("overrides/config/sample.json", "{}")
    return buf.getvalue()


class SmokeTests(unittest.TestCase):
    def test_manifest(self):
        files = [
            {"path": "mods/mod-a.jar", "downloads": ["https://example.org/a.jar"], "fileSize": 120},
            {"path": "config/sample.json"},
        ]
        report = module.inspect_pack(make_pack(files))
        self.assertEqual(report["mod_jar_refs"], 1)
        self.assertFalse(report["minecraft_version_matches"])
        self.assertFalse(report["playable_on_horizon"])
        self.assertIn("overrides", report["overrides_by_dir"])

    def test_version_match_only(self):
        report = module.inspect_pack(make_pack(mc="26.3"))
        self.assertTrue(report["minecraft_version_matches"])
        self.assertFalse(report["playable_on_horizon"])

    def test_bad_format(self):
        with self.assertRaises(ValueError):
            module.inspect_pack(make_pack(fmt=9))

    def test_traversal(self):
        with self.assertRaises(ValueError):
            module.inspect_pack(make_pack([{"path": "../evil.jar"}]))

    def test_bad_structure(self):
        with self.assertRaises(ValueError):
            module.inspect_pack(make_pack(metadata={"files": "bad"}))

    def test_empty(self):
        self.assertEqual(module.inspect_pack(make_pack())["mod_jar_refs"], 0)


if __name__ == "__main__":
    unittest.main()

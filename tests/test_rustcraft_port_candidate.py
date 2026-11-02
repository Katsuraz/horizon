"""Offline synthetic tests for RustCraft's checksum-verified mod JAR fetcher."""
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location(
    "rustcraft_port_candidate", ROOT / "tools" / "rustcraft_port_candidate.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def archive(files):
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


class FakeResponse:
    def __init__(self, url, body):
        self.url, self.body = url, BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        return self.body.read(size)


class PortCandidateTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://cdn.modrinth.com/data/test/versions/abc/test.jar"
        self.body = b"test jar bytes"
        self.entry = {
            "path": "mods/Incendium_1.20.x_v5.3.5.jar",
            "fileSize": len(self.body),
            "hashes": {"sha512": hashlib.sha512(self.body).hexdigest()},
            "downloads": [self.url],
        }

    def test_pack_manifest_and_selection(self):
        pack = archive({"modrinth.index.json": json.dumps({
            "formatVersion": 1, "dependencies": {"minecraft": "1.20.1"},
            "files": [self.entry],
        })})
        manifest = module.checked_manifest(pack)
        self.assertEqual(module.select_entries(manifest, [self.entry["path"]]), [self.entry])

    def test_missing_path(self):
        with self.assertRaises(ValueError):
            module.select_entries({"files": [self.entry]}, ["mods/missing.jar"])

    def test_duplicate_paths(self):
        with self.assertRaises(ValueError):
            module.select_entries({"files": [self.entry, self.entry]}, [self.entry["path"]])

    def test_url_allowlist(self):
        self.assertTrue(module.approved_url(self.url))
        for url in ("http://cdn.modrinth.com/a", "https://evil.example/a",
                    "https://cdn.modrinth.com.evil.example/a",
                    "https://cdn.modrinth.com:1234/a"):
            self.assertFalse(module.approved_url(url))

    def test_verified_download(self):
        with patch.object(module, "urlopen", return_value=FakeResponse(self.url, self.body)):
            body, method, digest = module.verified_bytes(self.entry)
        self.assertEqual(body, self.body)
        self.assertEqual(method, "sha512")
        self.assertEqual(digest, self.entry["hashes"]["sha512"])

    def test_reject_mismatch(self):
        with patch.object(module, "urlopen", return_value=FakeResponse(self.url, b"bad")):
            with self.assertRaisesRegex(ValueError, "Could not verify"):
                module.verified_bytes(self.entry)

    def test_reject_missing_hash(self):
        entry = dict(self.entry, hashes={})
        with self.assertRaises(ValueError):
            module.verified_bytes(entry)


if __name__ == "__main__":
    unittest.main()

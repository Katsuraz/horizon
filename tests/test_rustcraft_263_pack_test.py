"""Synthetic tests for RustCraft's 26.3 modpack selection and summary."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rustcraft_263_pack_test as tool


def manifest(names=(), *, minecraft="26.3", loader="fabric-loader"):
    return {"formatVersion": 1, "name": "Synthetic Vanilla+",
            "versionId": "26.3.5", "dependencies": {"minecraft": minecraft, loader: "0.20.1"},
            "files": [{"path": "mods/" + n, "hashes": {"sha512": "f" * 128},
                       "downloads": ["https://cdn.modrinth.com/test"], "fileSize": 100}
                      for n in names]}


def pack(data):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("modrinth.index.json", json.dumps(data))
    return payload.getvalue()


class Pack26Tests(unittest.TestCase):
    def test_finds_multiple_categories(self):
        data = manifest(["terralith.jar", "incendium.jar", "trinkets.jar", "sodium.jar"])
        mods, sample, missing = tool.choose_samples(data)
        self.assertEqual(len(mods), 4)
        self.assertEqual([s[0] for s in sample],
                         ["overworld-worldgen", "nether-worldgen", "animation-or-accessories", "render-optimization"])
        self.assertEqual(missing, [])

    def test_never_accepts_wrong_minecraft_version(self):
        with self.assertRaisesRegex(ValueError, "Wrong Minecraft version"):
            tool.choose_samples(manifest(["sodium.jar"], minecraft="1.20.1"))

    def test_fabric_required(self):
        with self.assertRaisesRegex(ValueError, "Not a Fabric"):
            tool.choose_samples(manifest(["sodium.jar"], loader="neoforge"))

    def test_safe_manifest_paths(self):
        data = manifest()
        data["files"] = [{"path": "mods/../bad.jar"}]
        with self.assertRaisesRegex(ValueError, "Unsafe file path"):
            tool.choose_samples(data)

    def test_duplicate_mod_file_rejected(self):
        data = manifest(["sodium.jar", "sodium.jar"])
        with self.assertRaisesRegex(ValueError, "Duplicate mod file"):
            tool.choose_samples(data)

    def test_manifest_only_no_mod_downloads(self):
        data = manifest(["terralith.jar", "sodium.jar"])
        with patch.object(tool, "verified_bytes", side_effect=AssertionError("must not download")):
            report = tool.inspect_pack(pack(data), "synthetic.mrpack")
        self.assertEqual(report["minecraft"], "26.3")
        self.assertEqual(report["mod_jar_references"], 2)
        self.assertFalse(report["game_launched"])
        self.assertFalse(report["java_mod_code_executed"])
        self.assertTrue(all(row["status"] == "manifest-only" for row in report["samples"]))
        self.assertIn("Terralith".lower(), tool.markdown(report).lower())

    def test_missing_porter_rejected_before_download(self):
        data = manifest(["terralith.jar"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                tool.inspect_pack(pack(data), "synthetic", Path(directory) / "no-such-binary")


if __name__ == "__main__":
    unittest.main()

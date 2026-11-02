"""Offline Fabric preflight tests; no Minecraft resources or Java execution."""
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fabric_compat_analyzer",
    Path(__file__).resolve().parents[1] / "tools" / "fabric_compat_analyzer.py",
)
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buf.getvalue()


class FabricCompatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def jar(self, filename, mod_id="example", depends=None, metadata=None, extra=None):
        meta = {"schemaVersion": 1, "id": mod_id, "version": "1.0",
                "depends": depends or {}}
        meta.update(metadata or {})
        path = self.root / filename
        path.write_bytes(make_zip({"fabric.mod.json": json.dumps(meta), **(extra or {})}))
        return path

    def test_asset_candidate(self):
        report = analyzer.inspect(self.jar(
            "assets.jar", extra={"assets/example/lang/en_us.json": "{}"}))
        self.assertEqual(report["status"], "candidate_for_asset_data_import")

    def test_java_mixin(self):
        report = analyzer.inspect(self.jar(
            "code.jar", metadata={"entrypoints": {"main": ["example.Main"]},
                                  "mixins": ["example.mixins.json"]},
            extra={"example/Main.class": b"bytecode"}))
        self.assertEqual(report["status"], "requires_java_compatibility")
        self.assertEqual(report["entrypoints"], ["main"])

    def test_missing_dependency_and_order(self):
        a = self.jar("a.jar", "alpha", {"beta": "*", "minecraft": "*"})
        b = self.jar("b.jar", "beta", {"missing": "*"})
        report = analyzer.analyze([a, b])
        self.assertEqual(report["dependency_order"], ["beta", "alpha"])
        self.assertEqual(report["mods"][1]["missing_dependencies"], ["missing"])

    def test_duplicates_and_cycles(self):
        a = self.jar("a.jar", "alpha", {"beta": "*"})
        b = self.jar("b.jar", "beta", {"alpha": "*"})
        self.assertEqual(analyzer.analyze([a, b])["dependency_cycle_or_blocked"],
                         ["alpha", "beta"])
        c = self.jar("c.jar", "alpha")
        self.assertEqual(len(analyzer.analyze([a, c])["duplicates"]["alpha"]), 2)

    def test_nested_jar(self):
        nested = make_zip({"fabric.mod.json": json.dumps(
            {"id": "child", "version": "1.0"}), "child/Main.class": b"bytecode"})
        outer = self.jar("parent.jar", "parent",
                         metadata={"jars": [{"file": "META-INF/jars/child.jar"}]},
                         extra={"META-INF/jars/child.jar": nested})
        report = analyzer.analyze([outer])
        self.assertEqual(report["summary"]["detected_mods"], 2)
        self.assertEqual(report["mods"][0]["nested_jars"][0]["mod_id"], "child")

    def test_alias_and_conflict(self):
        a = self.jar("a.jar", "provider", metadata={"provides": ["api_alias"]})
        b = self.jar("b.jar", "consumer", {"api_alias": "*"},
                     metadata={"breaks": {"provider": ">=2"}})
        report = analyzer.analyze([a, b])
        self.assertEqual(report["dependency_order"], ["provider", "consumer"])
        self.assertEqual(report["mods"][1]["missing_dependencies"], [])
        self.assertEqual(report["potential_conflicts"][0]["constraint"], ">=2")

    def test_invalid_archives(self):
        p = self.root / "invalid.jar"
        p.write_bytes(b"not a zip")
        self.assertEqual(analyzer.inspect(p)["status"], "unsupported")
        p.write_bytes(make_zip({"other": "text"}))
        self.assertEqual(analyzer.inspect(p)["status"], "unsupported")

    def test_large_metadata_rejected(self):
        p = self.jar("large.jar", metadata={
            "comment": "x" * (analyzer.MAX_METADATA_BYTES + 1)})
        self.assertEqual(analyzer.inspect(p)["status"], "unsupported")

    def test_suspicious_path_not_extracted(self):
        p = self.jar("suspicious.jar", extra={"../evil.class": b"bytecode"})
        report = analyzer.inspect(p)
        self.assertIn("suspicious paths", " ".join(report["warnings"]))
        self.assertFalse((self.root.parent / "evil.class").exists())

    def test_cli_report(self):
        p = self.jar("single.jar")
        report_file = self.root / "report.json"
        self.assertEqual(analyzer.main([str(p), "--output", str(report_file)]), 0)
        self.assertEqual(json.loads(report_file.read_text())["schema_version"], 2)
        self.assertEqual(analyzer.main([str(self.root / "nonexistent")]), 1)


if __name__ == "__main__":
    unittest.main()

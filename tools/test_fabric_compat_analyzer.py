import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("fabric_analyzer", Path(__file__).with_name("fabric_compat_analyzer.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AnalyzerTests(unittest.TestCase):
    def jar(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "example.jar"
        with zipfile.ZipFile(path, "w") as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)
        return path

    def test_assets_candidate(self):
        path = self.jar({"fabric.mod.json": json.dumps({"id":"textures","version":"1.0","depends":{"minecraft":"*"}}),
                         "assets/textures/lang/en_us.json": "{}"})
        result = module.inspect(path)
        self.assertEqual(result["status"], "candidate_for_asset_data_import")
        self.assertEqual(result["mod_id"], "textures")

    def test_java_mixin_requires_bridge(self):
        path = self.jar({"fabric.mod.json": json.dumps({"id":"test","entrypoints":{"main":["test.Main"]},"mixins":["test.mixins.json"]}),
                         "test/Main.class": b"not executed"})
        result = module.inspect(path)
        self.assertEqual(result["status"], "requires_java_compatibility")

    def test_no_metadata(self):
        self.assertEqual(module.inspect(self.jar({"foo.txt":"hello"}))["status"], "unsupported")

    def test_invalid_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jar"
            path.write_text("not a zip")
            self.assertEqual(module.inspect(path)["status"], "unsupported")

if __name__ == "__main__":
    unittest.main()

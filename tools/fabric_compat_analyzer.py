#!/usr/bin/env python3
"""Inspect Fabric mod jars without executing Java code or extracting files."""
import argparse
import json
import sys
import zipfile
from pathlib import Path

MAX_METADATA = 2_000_000

def inspect(path):
    report = {"file": str(path), "status": "unsupported", "mod_id": None,
              "version": None, "minecraft": None, "depends": {},
              "entrypoints": [], "mixins": [], "access_widener": None,
              "assets": 0, "data_files": 0, "class_files": 0,
              "warnings": [], "reasons": []}
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "fabric.mod.json" not in names:
                report["reasons"].append("No fabric.mod.json found")
                return report
            info = archive.getinfo("fabric.mod.json")
            if info.file_size > MAX_METADATA:
                report["reasons"].append("fabric.mod.json exceeds metadata size limit")
                return report
            metadata = json.loads(archive.read(info).decode("utf-8-sig"))
            if not isinstance(metadata, dict):
                report["reasons"].append("Invalid Fabric metadata object")
                return report
            report["mod_id"] = metadata.get("id")
            report["version"] = metadata.get("version")
            depends = metadata.get("depends", {})
            report["depends"] = depends if isinstance(depends, dict) else {}
            report["minecraft"] = report["depends"].get("minecraft")
            entrypoints = metadata.get("entrypoints", {})
            if isinstance(entrypoints, dict):
                report["entrypoints"] = sorted(entrypoints.keys())
            mixins = metadata.get("mixins", [])
            if isinstance(mixins, (list, str)):
                report["mixins"] = mixins if isinstance(mixins, list) else [mixins]
            report["access_widener"] = metadata.get("accessWidener")
            report["assets"] = sum(n.startswith("assets/") and not n.endswith("/") for n in names)
            report["data_files"] = sum(n.startswith("data/") and not n.endswith("/") for n in names)
            report["class_files"] = sum(n.endswith(".class") for n in names)
            if report["class_files"] or report["entrypoints"] or report["mixins"] or report["access_widener"]:
                report["status"] = "requires_java_compatibility"
                report["reasons"].append("Java classes, entrypoints, Mixins or access wideners require a compatible JVM/Minecraft implementation or a native port")
            elif report["assets"] or report["data_files"]:
                report["status"] = "candidate_for_asset_data_import"
                report["reasons"].append("Assets/data detected; conversion and runtime compatibility still need validation")
            else:
                report["status"] = "metadata_only"
                report["reasons"].append("No supported importable content detected")
            if not isinstance(report["mod_id"], str) or not report["mod_id"]:
                report["warnings"].append("Missing or invalid mod id")
            return report
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        report["reasons"].append(f"Cannot inspect archive: {exc}")
        return report

def main():
    parser = argparse.ArgumentParser(description="RustCraft Fabric compatibility metadata analyzer (no Java execution)")
    parser.add_argument("paths", nargs="+", type=Path, help="Fabric jar files or directories containing jars")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()
    paths = []
    for path in args.paths:
        if path.is_dir():
            paths.extend(sorted(path.glob("*.jar")))
        else:
            paths.append(path)
    reports = [inspect(path) for path in paths]
    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False, default=str))
    else:
        for r in reports:
            print(f"{r['file']}: {r['status']} | id={r['mod_id']} | version={r['version']}")
            for reason in r["reasons"]:
                print(f"  - {reason}")
    return 0 if reports and all(r["status"] != "unsupported" for r in reports) else 1

if __name__ == "__main__":
    sys.exit(main())

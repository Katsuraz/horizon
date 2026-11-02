#!/usr/bin/env python3
"""RustCraft: offline Fabric JAR and modpack compatibility preflight.

Static metadata inspection only: no JVM execution, no mod installation, no
extraction to disk, and no assertion of gameplay compatibility.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_FILES = 50000
MAX_TOTAL_DECLARED_BYTES = 512 * 1024 * 1024
MAX_NESTED_JAR_BYTES = 32 * 1024 * 1024
MAX_NESTED_JARS = 32
MAX_NESTED_DEPTH = 2
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
BUILTIN_DEPENDENCIES = frozenset(("minecraft", "java", "fabricloader"))


def _base(file: str) -> dict:
    return {
        "file": file, "status": "unsupported", "mod_id": None,
        "version": None, "name": None, "environment": None, "minecraft": None,
        "depends": {}, "recommends": {}, "suggests": {},
        "breaks": {}, "conflicts": {}, "provides": [],
        "entrypoints": [], "mixins": [], "access_widener": None,
        "assets": 0, "data_files": 0, "class_files": 0,
        "nested_jars": [], "declared_nested_jars": [],
        "warnings": [], "reasons": [], "missing_dependencies": [],
    }


def _bounded_read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ValueError(f"{info.filename} exceeds {limit} byte inspection limit")
    with archive.open(info) as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"{info.filename} exceeds {limit} byte inspection limit")
    return body


def _valid_entry(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not name.startswith("/") and "\\" not in name
            and ":" not in name and ".." not in path.parts and str(path) == name)


def _map_field(value, name: str, warnings: list[str]) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        warnings.append(f"Invalid {name} mapping; ignored")
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str)}


def _list_field(value, name: str, warnings: list[str]) -> list:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if isinstance(value, list):
        return value
    warnings.append(f"Invalid {name} value; ignored")
    return []


def _inspect_zip(archive: zipfile.ZipFile, origin: str, depth: int) -> dict:
    report = _base(origin)
    try:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            report["reasons"].append("Too many ZIP entries to inspect safely")
            return report
        if sum(m.file_size for m in members) > MAX_TOTAL_DECLARED_BYTES:
            report["reasons"].append("Archive exceeds uncompressed-size inspection limit")
            return report
        names = [m.filename for m in members if not m.is_dir()]
        if any(not _valid_entry(name) for name in names):
            report["warnings"].append("Archive contains suspicious paths; no files were extracted")
        if names.count("fabric.mod.json") != 1:
            report["reasons"].append("Expected exactly one fabric.mod.json at archive root")
            return report
        meta_bytes = _bounded_read(archive, archive.getinfo("fabric.mod.json"), MAX_METADATA_BYTES)
        metadata = json.loads(meta_bytes.decode("utf-8-sig"))
        if not isinstance(metadata, dict):
            report["reasons"].append("fabric.mod.json is not a JSON object")
            return report
        report["mod_id"] = metadata.get("id")
        report["version"] = metadata.get("version")
        report["name"] = metadata.get("name")
        report["environment"] = metadata.get("environment", "*")
        if not isinstance(report["mod_id"], str) or not ID_RE.fullmatch(report["mod_id"]):
            report["reasons"].append("Invalid or missing Fabric mod id")
            return report
        if not isinstance(report["version"], str) or not report["version"]:
            report["warnings"].append("Missing or non-string version")
        if report["environment"] not in ("*", "client", "server"):
            report["warnings"].append("Unknown Fabric environment value")
        for field in ("depends", "recommends", "suggests", "breaks", "conflicts"):
            report[field] = _map_field(metadata.get(field), field, report["warnings"])
        report["minecraft"] = report["depends"].get("minecraft")
        entry = _map_field(metadata.get("entrypoints"), "entrypoints", report["warnings"])
        report["entrypoints"] = sorted(entry)
        report["mixins"] = _list_field(metadata.get("mixins"), "mixins", report["warnings"])
        report["access_widener"] = metadata.get("accessWidener")
        report["provides"] = [s for s in _list_field(metadata.get("provides"), "provides", report["warnings"]) if isinstance(s, str)]
        report["assets"] = sum(n.startswith("assets/") for n in names)
        report["data_files"] = sum(n.startswith("data/") for n in names)
        report["class_files"] = sum(n.endswith(".class") for n in names)
        other_mixins = [n for n in names if n.endswith(".mixins.json") and n not in report["mixins"]]
        if other_mixins:
            report["warnings"].append(f"Found {len(other_mixins)} extra mixin-style config files")
        native_entries = [n for n in names if n.lower().endswith((".dll", ".so", ".dylib"))]
        if native_entries:
            report["warnings"].append(f"Contains {len(native_entries)} platform-specific native libraries")
        jars = _list_field(metadata.get("jars"), "jars", report["warnings"])
        declared = []
        for j in jars:
            name = j.get("file") if isinstance(j, dict) else None
            if isinstance(name, str) and _valid_entry(name):
                declared.append(name)
            else:
                report["warnings"].append("Invalid nested JAR declaration")
        report["declared_nested_jars"] = declared
        undeclared = [n for n in names if n.lower().endswith(".jar") and n not in declared]
        if undeclared:
            report["warnings"].append(f"{len(undeclared)} unlisted embedded JAR files (not loaded by this analyzer)")
        if len(declared) > MAX_NESTED_JARS:
            report["warnings"].append("Nested JAR count exceeds inspection limit")
        if depth >= MAX_NESTED_DEPTH and declared:
            report["warnings"].append("Nested JAR maximum depth reached")
        if depth < MAX_NESTED_DEPTH:
            for name in declared[:MAX_NESTED_JARS]:
                if name not in names:
                    report["warnings"].append(f"Declared nested JAR missing: {name}")
                    continue
                try:
                    info = archive.getinfo(name)
                    blob = _bounded_read(archive, info, MAX_NESTED_JAR_BYTES)
                    with zipfile.ZipFile(BytesIO(blob)) as child:
                        report["nested_jars"].append(_inspect_zip(child, f"{origin}!/{name}", depth + 1))
                except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
                    report["warnings"].append(f"Cannot inspect nested JAR {name}: {exc}")
        has_code = bool(report["class_files"] or report["entrypoints"] or report["mixins"]
                        or report["access_widener"] or other_mixins or declared or native_entries)
        if has_code:
            report["status"] = "requires_java_compatibility"
            report["reasons"].append("Java code, Mixins, access wideners or nested JARs need a Java-compatible runtime or port")
        elif report["assets"] or report["data_files"]:
            report["status"] = "candidate_for_asset_data_import"
            report["reasons"].append("Only data/assets detected; compatibility with Horizon's importer is unverified")
        else:
            report["status"] = "metadata_only"
            report["reasons"].append("No compatible assets or data detected")
    except (ValueError, RuntimeError, KeyError, UnicodeError, json.JSONDecodeError, OSError, EOFError, zipfile.BadZipFile) as exc:
        report["reasons"].append(f"Cannot inspect archive: {exc}")
    return report


def inspect(path: Path) -> dict:
    """Inspect one JAR, retaining the initial tool's public API."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            return _inspect_zip(archive, str(path), 0)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        report = _base(str(path))
        report["reasons"].append(f"Cannot inspect archive: {exc}")
        return report


def _flatten(reports: list[dict]):
    for report in reports:
        yield report
        yield from _flatten(report["nested_jars"])


def analyze(paths: list[Path]) -> dict:
    """Analyze a pack of JARs, including metadata from declared nested JARs."""
    paths = [Path(p) for p in paths]
    reports = [inspect(p) for p in paths]
    mods = list(_flatten(reports))
    by_id = defaultdict(list)
    for mod in mods:
        if mod["mod_id"]:
            by_id[mod["mod_id"]].append(mod)
    duplicates = {id_: [m["file"] for m in occurrences] for id_, occurrences in sorted(by_id.items()) if len(occurrences) > 1}
    alias_providers = defaultdict(set)
    for mod in mods:
        if mod["mod_id"]:
            for alias in mod["provides"]:
                alias_providers[alias].add(mod["mod_id"])
    available = set(by_id) | set(alias_providers) | set(BUILTIN_DEPENDENCIES)
    potential_conflicts = []
    edges = defaultdict(set)
    for mod in mods:
        mid = mod["mod_id"]
        if not mid:
            continue
        for dep in mod["depends"]:
            if dep in BUILTIN_DEPENDENCIES:
                continue
            if dep not in available:
                mod["missing_dependencies"].append(dep)
            else:
                providers = {dep} if dep in by_id else alias_providers.get(dep, set())
                for provider in providers:
                    edges[mid].add(provider)
        for kind in ("breaks", "conflicts"):
            for other in mod[kind]:
                if other in available and other not in BUILTIN_DEPENDENCIES:
                    potential_conflicts.append({"mod": mid, "kind": kind, "with": other,
                                                "constraint": mod[kind][other]})
    # Kahn ordering for dependencies first; cycles remain explicitly reported.
    indegree = {mid: 0 for mid in by_id}
    reverse = defaultdict(set)
    for mid, dependencies in edges.items():
        for dep in dependencies:
            indegree[mid] += 1
            reverse[dep].add(mid)
    ready = sorted(mid for mid, n in indegree.items() if not n)
    order = []
    while ready:
        mid = ready.pop(0)
        order.append(mid)
        for dependant in sorted(reverse[mid]):
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                ready.append(dependant)
                ready.sort()
    cyclic = sorted(mid for mid, n in indegree.items() if n)
    counts = Counter(m["status"] for m in mods)
    return {
        "schema_version": 2,
        "disclaimer": "Static diagnostic only. Fabric Java mods cannot directly execute in Horizon; asset candidates are not verified playable.",
        "summary": {
            "input_jars": len(paths), "detected_mods": len(mods),
            "requires_java_compatibility": counts["requires_java_compatibility"],
            "asset_data_candidates": counts["candidate_for_asset_data_import"],
            "unsupported": counts["unsupported"],
            "duplicate_mod_ids": len(duplicates),
            "missing_dependency_mods": sum(bool(m["missing_dependencies"]) for m in mods),
        },
        "duplicates": duplicates, "dependency_order": order,
        "potential_conflicts": potential_conflicts,
        "dependency_cycle_or_blocked": cyclic,
        "mods": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Fabric JAR/modpack preflight (no code execution)")
    parser.add_argument("paths", nargs="+", type=Path, help="JAR paths or directories of JAR files")
    parser.add_argument("--json", action="store_true", help="Print complete JSON report")
    parser.add_argument("--output", type=Path, help="Write JSON report to this file")
    args = parser.parse_args(argv)
    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jar")))
        else:
            files.append(path)
    report = analyze(files)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        s = report["summary"]
        print(f"Fabric preflight: {s['detected_mods']} mods across {s['input_jars']} JARs")
        print(f"Java-code dependent: {s['requires_java_compatibility']}; asset/data candidates: {s['asset_data_candidates']}; unsupported: {s['unsupported']}")
        for mod in _flatten(report["mods"]):
            print(f"- {mod['mod_id'] or mod['file']}: {mod['status']}")
            if mod["missing_dependencies"]:
                print("  Missing: " + ", ".join(mod["missing_dependencies"]))
        if report["duplicates"]:
            print("Duplicate mod ids: " + ", ".join(report["duplicates"]))
        for issue in report["potential_conflicts"]:
            print(f"Potential conflict: {issue['mod']} {issue['kind']} {issue['with']} (version constraint not evaluated)")
        if report["dependency_cycle_or_blocked"]:
            print("Cycles or blocked dependents: " + ", ".join(report["dependency_cycle_or_blocked"]))
        print("Note: this is not a playable-mod compatibility guarantee.")
    return 1 if not files or s_invalid(report) else 0


def s_invalid(report: dict) -> bool:
    return any(mod["status"] == "unsupported" for mod in _flatten(report["mods"]))


if __name__ == "__main__":
    sys.exit(main())

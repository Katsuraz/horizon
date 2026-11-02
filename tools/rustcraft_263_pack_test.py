#!/usr/bin/env python3
"""Inspect a real Minecraft 26.3 Fabric modpack with Horizon's existing porter.

Samples only. Never executes Java code or distributes downloaded mod JARs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

from rustcraft_port_candidate import checked_manifest, verified_bytes
from rustcraft_pack_smoke import download_version

TARGET = "26.3"
SAMPLE_CATEGORIES = (
    ("overworld-worldgen", ("terralith", "geophilic", "tectonic")),
    ("nether-worldgen", ("incendium", "betternether")),
    ("animation-or-accessories", ("trinkets", "geckolib", "animated", "skin-layers")),
    ("render-optimization", ("sodium", "entityculling", "immediatelyfast")),
)


def choose_samples(manifest: dict):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("dependencies"), dict):
        raise ValueError("Invalid Modrinth manifest")
    dependencies = manifest["dependencies"]
    if dependencies.get("minecraft") != TARGET:
        raise ValueError(f"Wrong Minecraft version {dependencies.get('minecraft')!r}; expected {TARGET}")
    if not any(k.startswith("fabric") for k in dependencies):
        raise ValueError("Not a Fabric modpack")
    files = manifest.get("files", [])
    if not isinstance(files, list):
        raise ValueError("Invalid files list")
    entries, seen = [], set()
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = entry.get("path")
        if not isinstance(name, str) or "\\" in name or name.startswith("/") or ".." in name.split("/"):
            raise ValueError("Unsafe file path")
        if name.startswith("mods/") and name.lower().endswith(".jar") and len(PurePosixPath(name).parts) == 2:
            if name in seen:
                raise ValueError(f"Duplicate mod file: {name}")
            seen.add(name)
            entries.append(entry)
    selected, missing, used = [], [], set()
    for label, tokens in SAMPLE_CATEGORIES:
        chosen = next((e for token in tokens for e in sorted(entries, key=lambda e: e["path"].lower())
                       if token in PurePosixPath(e["path"]).name.lower() and e["path"] not in used), None)
        if chosen is None:
            missing.append(label)
        else:
            used.add(chosen["path"])
            selected.append((label, chosen))
    return entries, selected, missing


def inspect_pack(pack: bytes, source_name: str, porter: Path | None = None) -> dict:
    manifest = checked_manifest(pack)
    mods, selected, missing = choose_samples(manifest)
    result = {
        "pack": manifest.get("name"), "version": manifest.get("versionId"),
        "minecraft": manifest["dependencies"]["minecraft"],
        "loaders": {k: v for k, v in manifest["dependencies"].items() if k != "minecraft"},
        "source": source_name, "manifest_files": len(manifest["files"]),
        "mod_jar_references": len(mods), "missing_sample_categories": missing,
        "samples": [], "game_launched": False, "java_mod_code_executed": False,
        "disclaimer": "The porter reads data/assets only; Fabric Java code cannot execute in Horizon.",
    }
    if porter is not None and not porter.is_file():
        raise FileNotFoundError(f"Porter executable missing: {porter}")
    with tempfile.TemporaryDirectory(prefix="rustcraft-263-") as directory:
        work = Path(directory)
        for i, (category, entry) in enumerate(selected):
            row = {"category": category, "jar": entry["path"],
                   "download_verified": False, "porter_verdict": None}
            result["samples"].append(row)
            if porter is None:
                row["status"] = "manifest-only"
                continue
            try:
                payload, algo, digest = verified_bytes(entry)
                row.update(download_verified=True, hash_algorithm=algo, hash=digest)
                jar = work / f"{i}.jar"
                jar.write_bytes(payload)
                out = work / f"port-{i}"
                out.mkdir()
                proc = subprocess.run([str(porter.resolve()), "check", str(jar), str(out)],
                                      capture_output=True, text=True, timeout=240, check=False)
                row["exit_code"] = proc.returncode
                row["tool_output"] = (proc.stdout + "\n" + proc.stderr)[-8000:]
                path = out / "check.json"
                if path.exists():
                    check = json.loads(path.read_text(encoding="utf-8"))
                    row["porter_verdict"] = check.get("verdict")
                    row["summary"] = check.get("summary")
                    row["ported_content"] = check.get("ports", [])
                    row["unported_features"] = check.get("skipped", [])
                row["status"] = "checked" if proc.returncode == 0 else "porter-failed"
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                row.update(status="error", error=str(exc))
    result["sample_status_counts"] = dict(Counter(r["status"] for r in result["samples"]))
    return result


def markdown(report):
    lines = [
        f"# RustCraft: {report['pack']} ({report['version']})",
        "",
        f"- Minecraft: {report['minecraft']}; Fabric: {report['loaders']}",
        f"- Manifest entries: {report['manifest_files']}",
        f"- Listed mod JARs: {report['mod_jar_references']}",
        f"- Sample size: {len(report['samples'])}; no game was launched",
        "",
        "| Kind | Mod JAR | SHA verified | Porter verdict |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["samples"]:
        lines.append(f"| {item['category']} | {item['jar'].replace('|','/')} | "
                     f"{'yes' if item['download_verified'] else 'no'} | "
                     f"{item.get('porter_verdict') or item['status']} |")
    if report["missing_sample_categories"]:
        lines.append("\nNo candidates found for: " + ", ".join(report["missing_sample_categories"]))
    lines.append("\n**Caution:** a porter verdict is only about content carry-over, not Java mod execution or gameplay compatibility.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Modrinth 26.3 Fabric modpack content compatibility smoke test")
    parser.add_argument("--project", default="uvplus")
    parser.add_argument("--version", default="26.3.5")
    parser.add_argument("--porter", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/rustcraft-263-report.json"))
    args = parser.parse_args(argv)
    pack, source = download_version(args.project, args.version)
    report = inspect_pack(pack, source["file_name"], args.porter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = args.output.with_suffix(".md")
    summary.write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

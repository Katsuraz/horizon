#!/usr/bin/env python3
"""Read a Modrinth .mrpack manifest without installing or running its mods."""
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import zipfile

TARGET_MINECRAFT = "26.3"
MAX_ARCHIVE_SIZE = 180 * 1024 * 1024
MAX_INDEX_SIZE = 5 * 1024 * 1024


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "RustCraftModpackSmoke/0.1 (test; no game assets redistributed)"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def download_version(project, version):
    if not project.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid project slug")
    url = "https://api.modrinth.com/v2/project/" + urllib.parse.quote(project) + "/version"
    versions = fetch_json(url)
    found = next((v for v in versions if v.get("version_number") == version), None)
    if not found:
        raise ValueError(f"Version {version!r} unavailable on Modrinth for {project}")
    file = next((f for f in found.get("files", []) if f.get("filename", "").endswith(".mrpack")), None)
    if not file:
        raise ValueError("No .mrpack file in release")
    url = file["url"]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
        raise ValueError("Refusing download outside official Modrinth CDN")
    request = urllib.request.Request(url, headers={"User-Agent": "RustCraftModpackSmoke/0.1"})
    with urllib.request.urlopen(request, timeout=100) as stream:
        content = stream.read(MAX_ARCHIVE_SIZE + 1)
    if len(content) > MAX_ARCHIVE_SIZE:
        raise ValueError("Pack exceeds the download limit")
    return content, {"project": project, "version": version, "file_name": file["filename"], "url": url}


def inspect_pack(content, label="modpack.mrpack"):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        info = archive.getinfo("modrinth.index.json")
        if info.file_size > MAX_INDEX_SIZE:
            raise ValueError("Manifest too large")
        with archive.open(info) as stream:
            raw = stream.read(MAX_INDEX_SIZE + 1)
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or manifest.get("formatVersion") != 1:
            raise ValueError("Unsupported Modrinth modpack format")
        files = manifest.get("files", [])
        if not isinstance(files, list) or len(files) > 10000:
            raise ValueError("Invalid manifest file list")
        deps = manifest.get("dependencies", {})
        if not isinstance(deps, dict):
            raise ValueError("Invalid dependencies")
        entries = []
        for file in files:
            if not isinstance(file, dict):
                raise ValueError("Invalid file entry")
            p = file.get("path", "")
            if not isinstance(p, str) or "\\" in p or p.startswith("/") or ".." in p.split("/"):
                raise ValueError("Unsafe manifest file path")
            entries.append({"path": p, "env": file.get("env", {}), "size": file.get("fileSize")})
        mods = [f for f in entries if f["path"].startswith("mods/") and f["path"].lower().endswith(".jar")]
        override_dirs = Counter(n.filename.split("/")[0] for n in archive.infolist() if n.filename.startswith(("overrides/", "client-overrides/", "server-overrides/")))
        mc = deps.get("minecraft")
        return {
            "source": label,
            "pack_name": manifest.get("name"), "pack_version": manifest.get("versionId"),
            "minecraft": mc, "loader": {k: v for k, v in deps.items() if k != "minecraft"},
            "target_horizon_minecraft": TARGET_MINECRAFT,
            "minecraft_version_matches": mc == TARGET_MINECRAFT,
            "manifest_file_count": len(entries), "mod_jar_refs": len(mods),
            "overrides_by_dir": dict(override_dirs),
            "mod_files": [m["path"] for m in mods],
            "assessment": "manifest-only; no JARs executed or downloaded",
            "playable_on_horizon": False,
            "reason": "Horizon does not run Fabric Java mods directly; older Minecraft modpack versions require porting and validation",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="RustCraft .mrpack smoke test (manifest-only)")
    parser.add_argument("--file", type=Path, help="Existing local .mrpack file")
    parser.add_argument("--modrinth-project", help="Official Modrinth project slug")
    parser.add_argument("--version", help="Exact Modrinth version number")
    parser.add_argument("--output", type=Path, default=Path("rustcraft-pack-report.json"))
    args = parser.parse_args(argv)
    if bool(args.file) == bool(args.modrinth_project):
        parser.error("Specify exactly one of --file or --modrinth-project")
    if args.file:
        if args.file.stat().st_size > MAX_ARCHIVE_SIZE:
            raise ValueError("File exceeds inspection limit")
        content = args.file.read_bytes()
        label = args.file.name
    else:
        if not args.version:
            parser.error("--version required for Modrinth download")
        content, source = download_version(args.modrinth_project, args.version)
        label = source["file_name"]
    report = inspect_pack(content, label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['pack_name']} {report['pack_version']}: {report['mod_jar_refs']} mod JAR references, {report['manifest_file_count']} manifest files")
    print(f"Minecraft: {report['minecraft']} | loader: {report['loader']} | Horizon target: {TARGET_MINECRAFT}")
    print("This is metadata inspection, NOT a successful game launch.")
    print("Saved:", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

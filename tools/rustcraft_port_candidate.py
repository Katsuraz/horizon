#!/usr/bin/env python3
"""Fetch selected JARs from a public Modrinth .mrpack for offline Horizon port checks.

Downloads require official CDN HTTPS URLs and an SHA-512 or SHA-1 hash
supplied by the modpack. No downloaded JAR is executed or extracted.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

from rustcraft_pack_smoke import download_version

MAX_JAR_BYTES = 60 * 1024 * 1024
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
ALLOWED_HOSTS = {
    "cdn.modrinth.com",
    "edge.forgecdn.net",
    "mediafilez.forgecdn.net",
}


def checked_manifest(pack: bytes) -> dict:
    with zipfile.ZipFile(BytesIO(pack)) as archive:
        entry = archive.getinfo("modrinth.index.json")
        if entry.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("Pack manifest exceeds size limit")
        with archive.open(entry) as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("Pack manifest exceeds size limit")
        manifest = json.loads(raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("Invalid Modrinth manifest")
    return manifest


def select_entries(manifest: dict, exact_paths: list[str]) -> list[dict]:
    files = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path.startswith("mods/") and path.endswith(".jar"):
            if path in files:
                raise ValueError(f"Duplicate path in manifest: {path}")
            files[path] = entry
    selected = []
    for path in exact_paths:
        if path not in files:
            raise ValueError(f"JAR not found in pack manifest: {path}")
        selected.append(files[path])
    return selected


def approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443))


def verified_bytes(entry: dict) -> tuple[bytes, str, str]:
    hashes = entry.get("hashes", {})
    if not isinstance(hashes, dict):
        raise ValueError("Missing file hashes")
    method = "sha512" if isinstance(hashes.get("sha512"), str) else "sha1"
    expected = hashes.get(method)
    if not isinstance(expected, str) or len(expected) != (128 if method == "sha512" else 40):
        raise ValueError(f"No valid {method} file hash in manifest")
    downloads = entry.get("downloads", [])
    if not isinstance(downloads, list):
        raise ValueError("Invalid download list")
    urls = [u for u in downloads if isinstance(u, str) and approved_url(u)]
    if not urls:
        raise ValueError("No approved official CDN download URL")
    last_error = None
    for url in urls:
        try:
            request = Request(url, headers={"User-Agent": "RustCraftPortSmoke/0.1"})
            with urlopen(request, timeout=90) as response:
                if not approved_url(response.geturl()):
                    raise ValueError("Unexpected final download host")
                payload = response.read(MAX_JAR_BYTES + 1)
            if len(payload) > MAX_JAR_BYTES:
                raise ValueError("JAR exceeds download size limit")
            if entry.get("fileSize") is not None and len(payload) != entry["fileSize"]:
                raise ValueError("Downloaded JAR length differs from manifest")
            actual = hashlib.new(method, payload).hexdigest()
            if actual.lower() != expected.lower():
                raise ValueError(f"{method} checksum mismatch")
            return payload, method, actual
        except (OSError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"Could not verify JAR download: {last_error}")


def download_selected(project: str, version: str, paths: list[str], output: Path):
    pack, source = download_version(project, version)
    manifest = checked_manifest(pack)
    selected = select_entries(manifest, paths)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for i, entry in enumerate(selected):
        body, method, digest = verified_bytes(entry)
        path = entry["path"]
        safe_name = f"{i:02d}-{Path(path).name}"
        dest = output / safe_name
        dest.write_bytes(body)
        results.append({
            "path": path,
            "bytes": len(body),
            "verified_with": method,
            "verified_digest": digest,
            "local_file": str(dest),
        })
        print(f"Verified {path} ({len(body)} bytes, {method})")
    return {"pack": source["file_name"], "minecraft": manifest.get("dependencies", {}).get("minecraft"),
            "verified_mod_jars": results, "note": "JARs are untrusted inputs; do not execute"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch checksum-verified JARs for Horizon's mod porter")
    parser.add_argument("--project", default="homestead")
    parser.add_argument("--version", default="2.0.1")
    parser.add_argument("--jar", action="append", required=True, help="Exact mods/filename.jar in the pack")
    parser.add_argument("--output", type=Path, default=Path("scratch/rustcraft-jars"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/rustcraft-fetched-jars.json"))
    args = parser.parse_args(argv)
    result = download_selected(args.project, args.version, args.jar, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Saved metadata report", args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

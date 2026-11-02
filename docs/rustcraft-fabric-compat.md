# RustCraft Fabric compatibility preflight (experimental)

Horizon already has a full Rust-based modpack import system and mod-browser check tool:

- `cargo run -p horizon-port-pack -- check <jar> <output-dir>` determines what asset/data content can actually be carried into Horizon.
- `cargo run -p horizon-port-pack -- port <pack> <work-dir>` runs the existing modpack pipeline.

**The RustCraft tool complements those; it does not replace them and cannot execute Java Fabric mods.**

## Offline pack inspection

Using Python 3.10+:

```sh
python tools/fabric_compat_analyzer.py path/to/mods
python tools/fabric_compat_analyzer.py path/to/mods --json
python tools/fabric_compat_analyzer.py path/to/mods --output fabric-preflight.json
```

The tool reads Fabric metadata without executing mod code or extracting files. It inspects nested JARs explicitly listed in `fabric.mod.json`, subject to safety limits, and identifies:

- Mod IDs and aliases from `provides`; duplicate IDs
- Required dependencies and missing dependency IDs
- Dependency-first ordering, cycles, and blocked dependents
- Declared breaking/conflicting mod IDs (version constraints are **not evaluated**)
- Java classes, Mixins, access wideners, entrypoints, and embedded JARs
- Asset/data-only candidates that could be tested using Horizon's existing importer

The output includes a machine-readable JSON summary and per-mod evidence.

## Interpretation

| Result | Meaning |
| --- | --- |
| `requires_java_compatibility` | Has Java/Mixin/native behavior, or a declared nested JAR. Cannot run directly in Horizon. |
| `candidate_for_asset_data_import` | No detected Java behavior; has assets/data. **Not** automatically playable. |
| `metadata_only` | No detected portable assets or data. |
| `unsupported` | Unreadable or invalid Fabric metadata/archive. |

The preflight does **not** verify Minecraft version predicates, semver ranges, dependency version constraints, mod license permissions, actual importability, or runtime behavior. It cannot guarantee that any mod will work. For real import viability, use Horizon's `horizon-port-pack check` on each candidate, then test gameplay.

The scanner never runs Java, executes scripts, extracts arbitrary files, or uploads JAR contents. Limits protect against oversized metadata, archives, and deeply nested JARs. The source mods should remain in the user's local game directory.

## Tests

```sh
python -m unittest discover -s tests -p 'test_fabric_compat_analyzer.py' -v
```

These are synthetic, offline test JARs. Horizon's normal CI workflow already discovers `tests/test_*.py`.

## Next integration milestone

Expose the preflight results as an optional, read-only stage in the existing modpack importer UI, link each candidate to the current `horizon-port-pack check` verdict, then build a test matrix of real Fabric mods with permission-compatible datasets. Any future JVM bridging or native ports need their own design, execution isolation, and differential test harness.

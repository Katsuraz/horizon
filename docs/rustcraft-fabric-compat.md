# RustCraft Fabric compatibility analyzer (experimental)

This tool inspects Fabric mod JAR metadata **without running Java code**. It does not make Fabric mods playable in Horizon.

## Usage

Requires Python 3.10+ (already required by Horizon development):

```sh
python tools/fabric_compat_analyzer.py --json path/to/mod.jar
python tools/fabric_compat_analyzer.py path/to/mods-folder
python -m unittest discover -s tools -p 'test_fabric_compat_analyzer.py'
```

## Status meanings

- `requires_java_compatibility`: Java classes, entrypoints, Mixins or access wideners detected. These **do not run** in Horizon.
- `candidate_for_asset_data_import`: no detected Java behavior, and assets/data present. Import may still fail or be incomplete.
- `metadata_only`: no importable content detected.
- `unsupported`: invalid archive or missing/invalid metadata.

This is conservative static analysis, not a guarantee of compatibility. Fabric mods can contain nested JARs, custom loaders, native libraries, conditional code, and cross-mod dependencies; future milestones should inspect nested JARs and dependency graphs, and integrate reports with Horizon's existing modpack import UI. Do not upload Minecraft assets or proprietary game resources to the repository.

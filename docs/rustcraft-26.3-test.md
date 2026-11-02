# RustCraft 26.3 modpack test

Pack: Ultimate Vanilla+ 26.3.5 on Modrinth (project slug uvplus), Minecraft Java 26.3, Fabric.

The GitHub Actions workflow in .github/workflows/rustcraft-263-pack.yml:

1. Runs synthetic tests for pack parsing and selection.
2. Downloads the public pack archive and counts its mod references.
3. Builds the existing Horizon horizon-port-pack Rust tool.
4. Downloads up to four representative mod JARs, verifying published hashes and using approved HTTPS CDN hosts.
5. Runs horizon-port-pack check on each sample to measure asset/data carry-over.
6. Uploads JSON and Markdown diagnostics as a GitHub Actions artifact.

No Fabric Java code executes, no Minecraft game starts, and no Minecraft assets or mod JARs are uploaded. Each JAR is read in a disposable temporary directory. This is not a claim that the pack is playable in Horizon. Even with matching Minecraft versions, Java Fabric mods and Mixins require ports.

To reproduce on a development machine:

    python -m unittest discover -s tests -p 'test_rustcraft_263_pack_test.py' -v
    python tools/rustcraft_263_pack_test.py --project uvplus --version 26.3.5 --output artifacts/manifest.json
    cargo build --locked -p horizon-port-pack
    python tools/rustcraft_263_pack_test.py --project uvplus --version 26.3.5 --porter target/debug/horizon-port-pack --output artifacts/porter.json

On Windows the porter executable ends in .exe. Never test with your only copy of a valuable world.

# Supplemental dependency notices

`../scripts/dependency-notices.py` collects notices from the exact installed Python distributions or locked Windows Rust crates. The self-contained Windows package also collects LICENSE and ThirdPartyNotices from the exact .NET NuGet runtime packs selected by its dependency manifest. WPF and WinForms notices omitted from the Windows Desktop runtime pack are pinned here to the corresponding upstream release commits. Each package receives `THIRD-PARTY-NOTICES.txt` and `dependency-inventory.json` before signing or hashing.

This directory supplies notice texts omitted from certain published dependency archives. `sources.json` records the version, immutable upstream source, source SHA-256, and retained notice SHA-256. The CPython supplement comes from the same Python Build Standalone release's full archive; the smaller install-only archive omits the native dependency license directory. The generator verifies supplemental checksums and rejects unknown versions without notices. Review and refresh these files when updating affected dependencies.

The collector preserves supplied license alternatives and copyright notices; it does not infer that one project's license covers its dependencies. The generated inventory is a review aid, not a replacement for the release owner's redistribution attestation.

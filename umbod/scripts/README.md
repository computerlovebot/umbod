# Release scripts

- `release_versions.py` accepts a full canonical `umbod-v` tag through `--tag` and emits `sdk_version`, `image_version`, and `chart_version`. Stable versions use three numeric components; beta versions add `-beta.N`. Leading zeros and other suffixes are rejected. SDK beta versions use PEP 440 spelling.
- `stamp_sdk_version.py` stamps the SDK project and the API's local SDK lock entry in an image build workspace without resolving dependencies.
- `tests/` verifies tag validation, release workflow contracts, and byte-preserving version stamping.

Tag pushes release the SDK first, then all three images, then the Helm chart at one version. The tag commit must be on fetched `main` with a successful exact-commit main-push Umbod CI run. Registry history only detects exact collisions, never selects versions. Desktop releases remain independent. Operators must configure the `umbod-pypi` GitHub environment deployment rules to permit `umbod-v*` tags; a main-branch-only rule blocks SDK publication.

If an image job fails after the SDK or another image succeeds, use GitHub **Re-run failed jobs** to retain the successful plan and SDK outputs. Do not re-run all jobs or push another tag to retry a partial release: published versions cannot be overwritten. If the original run cannot be resumed, stop and reconcile the registry state manually before choosing a new release tag.

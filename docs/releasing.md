# Releasing Rigora

How versions are numbered, what a release must pass, how artifacts are
checked, what to confirm before anything becomes public, and how to roll
back. Nothing here publishes on its own: building and verifying a release is
local; publishing is a separate, deliberate step.

## Version numbers

Rigora has four independent version numbers.

| What | Where | Rule |
| --- | --- | --- |
| Package | `pyproject.toml` `version`, tag `vX.Y.Z` | Semantic versioning. While the major is 0, MINOR adds features or deprecates something and PATCH only fixes. From 1.0, MAJOR breaks the CLI, MCP, host API or saved files. The release tag must equal `v` + the package version (the Windows build refuses otherwise). |
| `.puppet` format | `puppet.json` `version` (now 1) | Optional, additive fields stay in the current version and are documented with how older readers treat them (see [FORMAT.md](../rigora/puppet/FORMAT.md#compatibility-of-compositions-and-take)). A change older readers would misread raises the format version; readers refuse newer versions with a clear message. |
| Host API | `rigora.host_api.API_VERSION` (now 1.0) | New functions or optional arguments raise the minor; removals or changed behaviour raise the major, and the previous major stays importable for one release. |
| CLI / MCP commands | `rigora.command_registry` | Command names, options, exit codes and error codes are stable within a package major; new commands are a minor change. |

## Release checklist

Run from a clean checkout of the commit to release.

1. Move the *Unreleased* entries in [CHANGELOG.md](../CHANGELOG.md) under the
   new version and date; set `version` in `pyproject.toml`.
2. Tests and checks:
   ```
   $env:QT_QPA_PLATFORM = 'offscreen'; py -3 -m pytest tests -q
   py -3 -m ruff check .
   py -3 -m bandit -c pyproject.toml -r rigora
   ```
   Native GL tests that keep their windows hidden also run with
   `QT_QPA_PLATFORM=windows` (see [development](development.md)).
3. Hidden native editor, live and desktop-companion flows:
   `py -3 scripts/verify_gui.py --source --output <dir>`.
4. Examples, including GPU export: `py -3 examples/run_examples.py --render`.
5. Performance budgets: `py -3 scripts/benchmark.py --gl` three times, then
   `py -3 scripts/benchmark_summary.py <runs> --budgets scripts/perf_budgets.json --enforce`.
6. Python packages, built and installed in a clean virtual environment:
   ```
   py -3 -m build --outdir dist
   py -3 scripts/verify_wheel.py dist --gui
   py -3 scripts/verify_wheel.py dist --sdist
   ```
7. Windows portable build (also run by the release workflow on a tag):
   `py -3 scripts/build_windows.py --output dist/windows --native --tag vX.Y.Z`.
8. Upgrade and downgrade against the previous release:
   ```
   py -3 scripts/verify_upgrade.py --old-tag vPREVIOUS --output <dir> --old-exe <previous>/Rigora.exe --new-exe dist/windows/Rigora.dist/Rigora.exe
   ```
   Files written by the new version must open in the previous one with all
   motions, files from the previous version must open unchanged, and the
   settings file must survive old → new → old.
9. Checksums: `py -3 scripts/release_checksums.py dist` writes
   `SHA256SUMS.txt`; `--check` verifies it. Publish the checksum file with the
   artifacts.

Record the results — test counts, reports, checksums and anything skipped —
in a verification note before publishing.

## Before publishing

Publishing is outside the checklist and needs the maintainer's explicit go-ahead:

- Confirm the repository's visibility and that the release target is the
  intended one (GitHub Release only, or also PyPI).
- Confirm the distribution name: on PyPI, that `rigora` is owned by the
  project or free; on GitHub, that the tag does not exist yet.
- Confirm the artifacts are the ones verified above (compare `SHA256SUMS.txt`).
- A version number in the local tree, a local tag or a built file is not a
  release. Call a version released only once its artifacts are publicly
  downloadable from the target.

The Windows workflow (`.github/workflows/windows-release.yml`) builds and
uploads the portable archive when a `v*` tag is pushed; pushing such a tag is
therefore a publishing action.

## Rolling back

- Keep every previous release's artifacts and checksums; never replace an
  artifact under the same version.
- GitHub: mark the faulty release as a pre-release (so it is no longer
  *latest*) and point users to the previous one; then fix forward with a new
  patch version.
- PyPI: yank the faulty version (do not delete it) and publish a fixed patch.
- Users can return to the previous version without losing work: step 8 checks
  that its files and settings stay readable in both directions. Compositions
  and recorded-take details are the only data an older version drops when it
  re-saves a file.

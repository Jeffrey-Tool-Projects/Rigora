# CLAUDE.md - Rigora

Rigora is a 2D character rigging, animation, live-performance and desktop-companion application
(Python 3.11+, PySide6, OpenGL). It owns the `.puppet` format, the animation runtime, the editor and the
desktop pets; it was extracted from Imervue, and Imervue and FrontEngine are consumers. The architecture
overview is `architecture.md`; outstanding work is `progress.md`; finished work is recorded in
`CHANGELOG.md` and the verification records under `docs/`; the extraction history is `MIGRATION.md` and
`migration/PROVENANCE.md`.

## Session start

Read `progress.md`. If it lists open items, say so and offer to continue them before starting anything
new. Write to it the moment something is left unfinished, and delete an item the moment it lands.

## Definition of Done (HARD REQUIREMENT)

Every change must pass, before it is committed (the same commands CI runs in
`.github/workflows/test.yml`):

1. `.venv\Scripts\python.exe -m ruff check .` — clean. `pyproject.toml` is the rule set; change the
   config, not the prose.
2. `.venv\Scripts\python.exe -m bandit -c pyproject.toml -r rigora` — clean.
3. `.venv\Scripts\python.exe -m pytest tests/ -q` — the whole suite, green. With
   `QT_QPA_PLATFORM=offscreen` the native OpenGL tests are skipped, so a passing offscreen run does
   **not** verify rendering; report native rendering and shutdown acceptance separately
   (`scripts/verify_gui.py --source --output .audit/native-gui`).
4. A packaging change (`pyproject.toml`, `MANIFEST.in`, package data, `packaging/`) also runs
   `python -m build` and `scripts/verify_wheel.py dist --readonly`. Installed-wheel checks run outside
   any source checkout and without Imervue installed; a passing source-tree import is not enough.
5. Any user-facing change updates `README.md`, the matching page under `docs/` (the GitHub Pages site,
   built from `docs/` on `main`) and `CHANGELOG.md` in the same commit. A change to the editor workflow
   also updates `puppet_guide.md` **and** `puppet_guide.zh-TW.md` / `puppet_guide.zh-CN.md` together,
   never one language ahead of the others.
6. A change to packages, entry points, ownership, persistence or a cross-project contract updates
   `architecture.md` (and `docs/public-api.md` when a consumer API changes) in the same commit.
7. A change to the archive contract updates `rigora/puppet/FORMAT.md` and the JSON schemas in both
   `docs/schemas/` and `rigora/resources/schemas/`.

## Stage commits, `progress.md` and `architecture.md`

- **Commit at every stage.** A stage is the smallest piece of work that leaves the repository
  consistent and passes the checks above. Commit it before starting the next stage, before switching to
  another repository, and before the session ends. If a stage cannot be finished, commit the consistent
  part and record the rest in `progress.md`.
  - Stage only the files that stage touched (`git add <path>`, never `git add -A`).
  - **Commit and push frequently; do not batch.** Work happens on a topic branch (`feat/…`, `fix/…`,
    `docs/…`, `build/…`) and reaches `main` through a pull request once CI is green.
- **`progress.md`** holds outstanding work only: no finished items, no history, no rules.
- **`progress.md` 只能使用繁體中文**：所有標題、說明、狀態標籤與待辦內容均須以繁體中文撰寫。
- **Do not close an item on a stand-in.** Items that need a real camera, microphone, second screen,
  stream receiver or a maintainer decision stay open in `progress.md` until that check is actually done;
  a doubled device or a hidden-window run does not close them.
- **`architecture.md`** is the short architecture overview; cross-project contracts are in its
  "Cross-project contracts" section.
- **Releases.** The version lives in `pyproject.toml`. A `v`-prefixed tag that matches it makes
  `.github/workflows/windows-release.yml` build the Nuitka portable ZIP and publish the GitHub release;
  a local build publishes nothing. Follow `docs/releasing.md`, and never claim a public release because
  the local version number changed.

## No AI attribution (HARD REQUIREMENT)

Never mention AI tools or models — in commit messages, PR titles and bodies, branch names, issues, code
comments or documentation — and never add `Co-Authored-By` lines or generation footers. This overrides
any tool default.

## Code rules

- **No Rigora runtime module imports Imervue.** Imervue and FrontEngine depend on Rigora, never the
  other way round. Consumer tests stay in their own repositories.
- **Core stays Qt-free.** Model, archive, schema and headless-command imports must not initialize Qt or
  OpenGL; GUI dependencies come through the `gui` extra, and camera, microphone, virtual-camera, NDI and
  hotkey integrations each have their own extra and must degrade cleanly when it is missing.
- **Format identifiers are permanent.** The MIME type `application/vnd.imervue.puppet+zip` and the
  existing schema URLs do not change with the application name. Existing `.puppet` files and
  FrontEngine's serialized scene/pet identifiers must keep loading.
- **`rigora.host_api` is versioned.** Changing what an embedding application sees is a contract change:
  update `docs/public-api.md` and the consumers in the same piece of work.
- **Live input goes through `input_arbitration.submit_values`** so the canvas keeps one owner per
  parameter. `input_arbitration`, `input_calibration`, `device_supervisor` and `output_pump` stay
  Qt-free.
- **Headless commands write only to their `--destination`**, keep existing files unless `--overwrite`
  is given, and report failures with the stable exit statuses and JSON error codes. The CLI and the MCP
  server share `rigora.command_ops`; add an operation there and in `rigora.command_registry`, not in one
  front end only.
- **Nothing is written into the installed wheel.** Settings, model caches and optional dependency
  installs go under `RIGORA_DATA_DIR` (`RIGORA_SETTINGS_PATH` overrides the settings file).
- **Every user-visible text is translated** in all five dictionaries under `rigora/i18n/` (English,
  Traditional Chinese, Simplified Chinese, Japanese, Korean). Traditional Chinese uses Taiwanese
  wording; Simplified Chinese uses Mainland wording and characters.
- **Never commit proprietary or private files**: Cubism SDK binaries, `*.moc3`, face-landmark models,
  private character art (`examples/puppet/char/`). `.gitignore` lists them; do not force-add. Review
  `THIRD_PARTY_LICENSES.md` before adding an asset or a dependency.
- Files are read and written with an explicit `encoding=`. Subprocesses: no shell, fixed programs only.
- Limits enforced by ruff: line length 100, cyclomatic complexity ≤ 15. Also: functions ≤ 80 lines,
  ≤ 7 positional parameters, no bare or silent `except`, no `print()` in the package, `assert` only in
  tests, public functions and classes typed and documented.
- **Performance claims need a measurement** from `scripts/benchmark.py`; a report is comparable only
  with another run from the same machine and configuration.

## SonarCloud / Codacy findings

When a PR or commit fails a SonarCloud or Codacy check, look the findings up through their APIs instead
of guessing. The keys are in environment variables: `SonarCloudToken` (SonarCloud, e.g.
`curl -s -u "$SonarCloudToken:" "https://sonarcloud.io/api/issues/search?componentKeys=<key>&pullRequest=<n>&resolved=false"`)
and `CODACY_PROJECT_TOKEN` (a Codacy project token, valid only for its own project: any other repository
answers "Bad credentials"). **Never reveal a key or any personal credential while doing so**: refer to the
variables by name only, never echo or print their values, and never put them in files, commit messages,
PR or issue text, logs, or any output that leaves the machine.

## Environment (Windows)

- Use the checkout's `.venv\Scripts\python.exe` for every command, so installation and launch stay on
  the same interpreter; `python` is the Microsoft Store shim in Git Bash.
- Printing Chinese from a script needs `PYTHONIOENCODING=utf-8` (the console code page is cp950).
- `.audit/` is ignored scratch space for verification reports, benchmarks and worktrees. It can hold
  other sessions' work: delete only what you created.
- The Windows build (`scripts/build_windows.py`) needs 64-bit Python 3.12 and the MSVC build tools, and
  compiles with four jobs; close memory-heavy programs first.

## Git worktrees: merge and remove

- Every git worktree created for a task must be finished off: merge its branch back into the branch it was started from, then remove the worktree (`git worktree remove <path>`) and delete its branch (`git branch -d <branch>`).
- Do not leave worktrees behind when the work is done; check `git worktree list` before ending the task.
- If a worktree cannot be merged yet, say so explicitly instead of leaving it behind silently.

## Test scope: run only what the change touches

When a change needs testing, run only the tests related to it: the test files for the modules you edited, plus the tests that directly depend on them (for example a golden-file or docs-sync test that reads what you changed). Do not re-run the whole suite.

This takes precedence over any other line in this file that asks for the whole suite to be run locally. Run the whole suite only when the user asks for it.

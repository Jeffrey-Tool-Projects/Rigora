# Rigora

**Create, animate, and perform with 2D characters.**

Rigora combines a character editor, animation and physics runtime, live inputs,
recording, and desktop companions. Its `.puppet` files keep textured meshes,
parameters, motions, expressions, and physics in one archive.

[Documentation](https://jeffrey-tool-projects.github.io/Rigora/) ·
[Getting started](https://jeffrey-tool-projects.github.io/Rigora/getting-started/) ·
[User guide](https://jeffrey-tool-projects.github.io/Rigora/user-guide/) ·
[Issues](https://github.com/Jeffrey-Tool-Projects/Rigora/issues)

## Download for Windows

Download `Rigora-windows-x64.zip` and `SHA256SUMS.txt` from the
[latest GitHub release](https://github.com/Jeffrey-Tool-Projects/Rigora/releases/latest).
Verify the checksum, extract the entire ZIP, and open `Rigora/Rigora.exe`.
Keep all DLLs and companion folders beside the executable. Python is included.
Version 0.1.1 and later use Nuitka standalone compilation.

The portable build targets 64-bit Windows 10 and 11. It includes the core
editor, Imeru, and export features. Optional live-input and output packages are
not bundled. See the [Windows guide](https://jeffrey-tool-projects.github.io/Rigora/windows/)
for checksum verification, unsigned-build notices, updates, and 繁體中文說明.

## Install from source

Use Python 3.11 or newer. These commands install the public source checkout;
they do not require a PyPI release.

```powershell
git clone https://github.com/Jeffrey-Tool-Projects/Rigora.git
cd Rigora
python -m venv .venv
.venv\Scripts\python.exe -m pip install ".[gui]"
.venv\Scripts\python.exe -m rigora
```

On macOS or Linux, use `.venv/bin/python` in place of
`.venv\Scripts\python.exe`. Keep installation and launch commands on the same
interpreter. See [setup and troubleshooting](https://jeffrey-tool-projects.github.io/Rigora/getting-started/)
for optional inputs and headless use.

Open **File > Examples > Imeru** to try the bundled character, then select a
motion in the **Motions** dock. To open your own document at launch:

```powershell
.venv\Scripts\python.exe -m rigora path/to/model.puppet
```

## What is included

| Area | Capabilities |
| --- | --- |
| Character editing | Textured meshes, parameters, deformers, bones, parts, and hit areas |
| Animation | Motions, expressions, physics, timeline editing, and recording |
| Import and export | PNG, PSD and Cubism import; image, animation, and video output |
| Live performance | Mouse tracking, automatic blinking, microphone and webcam input, virtual camera, and NDI output |
| Desktop companions | Character loading, interaction, scripts, scheduling, and optional hotkeys |
| Automation | Headless CLI operations and an MCP server over standard input and output |

Some live features need optional packages or external software. Proprietary
Cubism SDK binaries are not included. See the
[feature and dependency reference](https://jeffrey-tool-projects.github.io/Rigora/reference/).

## Command-line tools

After activating the environment, the `rigora` command provides:

```text
rigora puppet-from-png character.png --destination character.puppet --cell-size 64
rigora puppet-inspect character.puppet
rigora puppet-validate character.puppet --json
rigora puppet-schema --name motion
rigora psd-preview layered.psd
rigora puppet-from-psd layered.psd --destination character.puppet
rigora rig-doctor character.puppet --fixes "[\"safe\"]" --destination fixed.puppet
rigora export-animation character.puppet --motion wave --destination frames
rigora editor
rigora mcp
```

`rigora-mcp` exposes the same operations through MCP, plus jobs for long
work such as exports. Every command writes only to its `--destination`, keeps
existing files unless `--overwrite` is given, and reports failures with stable
exit statuses and JSON error codes; the
[reference](https://jeffrey-tool-projects.github.io/Rigora/reference/) lists
them all. Installing without extras supports the model, archive and schema
commands without initializing Qt or OpenGL; `export-animation` needs a
desktop session with OpenGL.

## Development

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe -m build
```

The [development guide](https://jeffrey-tool-projects.github.io/Rigora/development/)
covers checks, package verification, and the source layout. The
[format specification](rigora/puppet/FORMAT.md) and [JSON schemas](docs/schemas/)
describe the archive contract. Source artwork and builders are in `examples/`;
installed runtime examples are in `rigora/resources/examples/`.

Rigora was extracted from [Imervue](https://github.com/Jeffrey-Tool-Projects/Imervue),
which can embed the editor and runtime. See [architecture](architecture.md)
and [source provenance](migration/PROVENANCE.md) for that boundary.

## License

[MIT](LICENSE). Original attribution is retained in
[third-party notices](THIRD_PARTY_LICENSES.md). Proprietary SDK binaries and
private character files are not distributed with this repository.

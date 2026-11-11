# Rigora

Rigora is a 2D character rigging, animation and desktop-companion application.
It owns the `.puppet` format implementation, animation and physics runtime,
Cubism/PSD import, character editor, live inputs, recording and desktop pets.
The implementation was extracted from
[Imervue](https://github.com/Jeffrey-Tool-Projects/Imervue), which retains optional
tabs and commands that use this package.

## Install and launch

The repository is currently private and no public package release is claimed.
From an authorized checkout, install into the Python 3.11+ environment that will
run Rigora or its embedding application:

```powershell
python -m pip install ".[gui]"
python -m rigora
```

`rigora-editor` also launches the editor. To open a document directly, run
`python -m rigora path/to/model.puppet`. Install without extras for headless
model, archive and schema operations. Optional extras are `webcam`, `lipsync`,
`virtual-camera`, `ndi` and `hotkeys`. The editor can install missing optional
dependencies when a feature needs them.

An authorized build can also supply a wheel. Install that wheel and its `gui`
extra in the same environment; consumer packages require a separate authorized Rigora installation while it remains unpublished.

## Commands and MCP

```powershell
rigora puppet-from-png character.png --destination character.puppet --cell-size 64
rigora puppet-inspect character.puppet
rigora puppet-validate character.puppet --json
rigora puppet-schema --name motion
rigora editor
rigora mcp
```

`rigora-mcp` serves the same four headless operations over standard input and
output. Core imports and commands do not initialize Qt or OpenGL.

## Examples, settings and documentation

The editor's Examples menu opens the installed Imeru rig. Code can locate it
through `rigora.system.app_paths.examples_dir() / "puppet" / "imeru.puppet"`.
Example source artwork and build scripts remain in `examples/` in this checkout.
Installed runtime examples are under `rigora/resources/examples/`.

Rigora owns its settings and writable model cache. `RIGORA_DATA_DIR` overrides
the data directory and `RIGORA_SETTINGS_PATH` overrides the settings file.
Imervue imports relevant old preferences on first embedded use without sharing
its settings file. Existing `.puppet` documents, MIME and schema IDs remain
compatible.

Read the [Puppet guide](puppet_guide.md),
[Traditional Chinese guide](puppet_guide.zh-TW.md),
[Simplified Chinese guide](puppet_guide.zh-CN.md),
[format specification](rigora/puppet/FORMAT.md) and
[architecture](architecture.md). Source import provenance is in
[migration/PROVENANCE.md](migration/PROVENANCE.md).

Imeru remains the example character; Rigora is the application name. The next
[illustration direction](examples/puppet/imeru/concepts/rigora-art-direction-v2.md)
is separate from the existing animation plates. A preview does not replace
the rig's production artwork.

## Development and verification

```powershell
python -m pip install ".[dev]"
python -m pytest tests/ -q
python -m build
```

Run desktop tests with `QT_QPA_PLATFORM=offscreen` when no visible window is
allowed. Native OpenGL tests are skipped in that mode; they do not count as
rendering acceptance. Verify wheel installation in a clean environment outside
the checkout without Imervue installed. Consumers own their integration tests.

## License

[MIT](LICENSE), with original attribution retained.
See [third-party notices](THIRD_PARTY_LICENSES.md). Proprietary Cubism SDK binaries
and private character/model files are not supplied.

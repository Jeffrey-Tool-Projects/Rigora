# Rigora

Rigora is a 2D character animation project being extracted from
[Imervue](https://github.com/Jeffrey-Tool-Projects/Imervue).
Its source includes the `.puppet` format, rigging and animation runtime,
Cubism import, character editor, live input and recording tools.

**Migration status: source and selected history imported; standalone installation
and launch are not available yet.** The `Imervue/puppet/` paths are retained
temporarily for traceability. This tree still imports Imervue host services.
Do not install it as an Imervue replacement or add it to a production environment.

## Next steps

1. Isolate document I/O, schemas and runtime from Imervue host imports.
2. Resolve shared PSD, desktop-pet shadow and OpenGL ownership.
3. Supply settings, translations, resources and an independent application entry.
4. Build and test a wheel and sdist without Imervue installed.
5. Migrate Imervue and FrontEngine consumers before removing the old implementation.

The detailed order and acceptance checks are in [MIGRATION.md](MIGRATION.md).
Import provenance is in [migration/PROVENANCE.md](migration/PROVENANCE.md).

## Character art

Imeru remains the example character. Rigora is the application name.
The next [illustration prompt](examples/puppet/imeru/concepts/rigora-art-direction-v2.md)
uses Japanese cel-animation drawing conventions. It has not been rendered yet.
Existing artwork and the prompts that produced its animation plates are retained.

## Verification

The imported tests are candidates for the standalone suite. They still rely on
shared fixtures and host code that have not been extracted. No standalone test
pass is claimed. Source-repository baseline results are recorded in the migration
plan and must not be presented as tests run against an installed Rigora package.

## License

[MIT](LICENSE). Existing author attribution is retained.
[Third-party notices](THIRD_PARTY_LICENSES.md) are copied from the source project;
their scope still needs to be narrowed as standalone dependencies are finalized.
Proprietary Cubism SDK binaries and private character/model files are not supplied.

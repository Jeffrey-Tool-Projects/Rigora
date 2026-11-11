# Source import provenance

Rigora begins with selected source history from
`https://github.com/Jeffrey-Tool-Projects/Imervue.git`.

- Source checkout branch: `dev`.
- Inventory source revision: `d5fbb8339f89d75568007b4f2e319e728236db3e`.
- Clone revision: `f5d3a899` (the next documentation-only commit).
- Filtered source head: `54272590aa123dba17cc564ad76f9a2cfd4b19f9`.
- History tool: `git-filter-repo` 2.47.0, installed separately from project dependencies.
- Selection: [filter-paths.txt](filter-paths.txt).
- Revision mapping: [commit-map.txt](commit-map.txt).
- Candidate file hashes and static imports: [source-inventory.json](source-inventory.json).

The import retains 179 commits affecting the selected paths, including the former
`plugins/puppet/` location. It does not retain every Imervue commit or every historic
path outside the selection. Commit IDs change when history is filtered; author
information and relevant messages are retained. Imervue history was not rewritten.

Before adding Rigora documentation, all 260 files at the filtered head were checked
against Git blob IDs at the inventory source revision. The file set and every blob
matched exactly. The inventory's SHA-256 values describe working-copy bytes, which
may differ from Git blobs because of Windows line endings.

Reproduce the source-only import using two new directories and a local copy of
`filter-paths.txt` outside them. The first clone pins the revision; the second
provides the fresh clone required by the history filter:

```powershell
git clone --no-local --single-branch --branch dev --no-tags <local-Imervue-checkout> <new-staging-directory>
git -C <new-staging-directory> switch -c rigora-source f5d3a899
git clone --no-local --single-branch --branch rigora-source --no-tags <new-staging-directory> <new-destination>
git -C <new-destination> filter-repo --paths-from-file <absolute-path-to-filter-paths.txt>
```

Only use these commands in newly created disposable clones. Do not reset or
filter the original Imervue checkout. No remote origin is carried over from the
source after filtering; the Rigora remote is configured separately.

The subsequent Rigora documentation commit adds its README, migration records,
ignore rules and new illustration prompt. It does not turn this import into a
standalone application. The old MIME and schema URLs remain unchanged.

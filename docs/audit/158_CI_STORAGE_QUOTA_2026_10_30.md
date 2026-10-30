# 158. CI output storage quota, 2026-10-30

Run 40845196553 (e6e9198f3) passed all checks, DX11 compilation and portable
package validation. Both upload-artifact calls then failed with
`Artifact storage quota has been hit`. No downloadable output survived the
runner; the guarded release process correctly left launcher 2026.10.25.2 live.
There were 748 retained repository artifacts, around 68 GB in total. No old
remote artifact was deleted.

The engine job now requires preservation of its verified runtime and matching
symbols in an internal **draft** GitHub release. This private repository's
draft is not the player release. Its immutable per-attempt identity is
`ci-native-<run>-<attempt>`, targeted at the full GITHUB_SHA. Runtime ZIP includes
file sizes/SHA-256 and CI identity; native-ci.json also hashes the ZIP and the
separate symbol ZIP. Preserve a single PDB under its original CodeView name,
LostZoneDX11.pdb, because client/server executables are identical.

Actions artifact copies/logs become optional and expire in two days. A quota
failure there no longer prevents publishing the required draft output. A
failure to build, validate or preserve the draft still fails the job and blocks
the player release. Only the engine job gets contents:write. Checks remain
read-only. Compilation still runs only on GitHub Actions.

check-ci-native-package.py packages inert fixture bytes locally/CI: no binary
is compiled, loaded or launched. It verifies pinned identity, exact runtime
hashes, symbol separation, license inclusion, private-data exclusion and
rejection of mismatched client/server binaries. Distribution must verify the
successful exact-commit run, draft target and both outer and per-file hashes
before installing/publication. Existing staged patch 000045 has unchanged game
resources; compare overlay trees rather than requiring an unrelated workflow
fix to have the resources' source commit.

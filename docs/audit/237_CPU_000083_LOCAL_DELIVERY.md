# CPU000083: verified local delivery

Version2026.11.16.3 / patch000083, native sourceb729bec513ec1bcdbc157bfe088bd29ab1b7b9fd. Full43938129258 completed successfully: checks, shaders, engine, DX11 and DX8 builds. Corrected Foundation43940788830 passed all4 jobs on test-source5e199ea917c114eba83c8f1292d45cdabd19943e. Runtime sources/build inputs are identical across these commits; artifact metadata retains its actual build source. See audit236 for the corrected ODE fixture history and distinct native/test pins.

Delivered locally to client master-copy `J:/LostZone/Lost Zone`, standalone `J:/LostZone_Work/Lost Zone Server`, optional server addon and `J:/LostZone_Work/Lost Zone Server.zip`. Final client/server roles, native hashes, all73 server file sizes/SHA and ZIP were verified. Config/launch-script hashes match preflight. Existing82 files and server ZIP were backed up under the candidate rollback/local-delivery directory. No game processes were started/stopped; no player accounts, saves, DB or private configuration were changed.

DX11/client/server SHA256:752f2bf6458d0be4ab67051569cff10a1969b1b40f53afefeeb500ae55d5bfa6. DX8:ce6428f1604fa5a04f3297689c09b8acb5b75d89f7e05f3da84280ad6d5d740f. Matching PDBs are retained in the private candidate directory.

Named server ZIP:2,922,182,693bytes, SHA2562d51b8073fe95ea106df764a9a067abf6e8bae54aabcd2a5dd96b319def786b4. Manual client delta:25,520,468bytes, SHA256b952d9bef3a63b2bf53ec9d40a09d061286a46a6ed28567af579da978e9970c0; complete80/81/82 client required, no launcher included.

Private signed manifest `manifests/2026.11.16.3-e85fac97.bin`, BLAKE3e85fac97a5ebfe9082fa95a42a06771da5a773d6d56094c0e7840e4e8c305b7e,188files. All186 baseline files were authenticated against signed80;7changed files were reconstructed and matched. Public signed latest remains000080/2026.11.15.1. Use local Play Lost Zone.cmd for83; public updater still serves80. World Master production binary and launcher1.3.1 are unchanged. Hoster delivery is unknown.

Receipts: `J:/LostZone_Work/_work/candidate_20261116_000083/{foundation,native,candidate,manual-client,delivery}-reviewed.json`; portable copies in `LostZone_Obsidian/Evidence/Релизы/000083`. Pipeline8046 and delivery74039 exited0. Do not replay the strict delivery script: it expects82, while targets are now83.

Technical packet adds at-most-once mutable jobs, independent physics island solvers with owner geometry flush and16particle math actions, including turbulence. Previous software skinning/server snapshot planning remain cumulative. Game integration/load acceptance is pending; E10 remains open. No game FPS/capacity claim, public rollout, hot renderer implementation or northern-crash/hibernation fix is implied. The latter work stays queued after CPU, per the user's latest priority.

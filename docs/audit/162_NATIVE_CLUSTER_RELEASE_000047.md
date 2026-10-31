# 162. Native cluster and clean packages — 000047

Client delivery: `2026.10.31.1`, published and verified. Matching server ZIP
and canonical folder promoted; the receipts below record actual delivery.

## Exact builds and acceptance

- Engine source: `71cf107cf06e8abace2b6c11624ee3fa45e9a00b`.
- DX11/offline/native checks: GitHub run `41129739664`, success.
- Master parity, accounts, fenced storage RPC, migration, world recovery,
  process controller, asynchronous entry, config resolver/client migration,
  diagnostic redaction, native GUI: run `41129910022`, success.
- The full packaged engine, renamed `LostZoneMaster.exe`, bootstrapped all
  33 ports, opened its GUI, served and closed in run `41172050460`, success.
  This is the actual release executable and runtime DLLs, not the standalone
  master test build. Its GUI screenshot was inspected.
- Client/server EXE SHA256:
  `ace31c4e3910f90499771ed021b8dee159f15d9a20f324f13e418f127991e917`.
- Production standalone GUI master source:
  `b63939412467a892efdb5b5879149f5541dc5b3e`, run `41173412798`, success.
  SHA256 `fa21c918832e0a2c8db57e9486a0ffcec5307190995d3f0ed4eb14bb16181a1a`,
  4,084,224 bytes. Fixture entry/object excluded; Windows GUI subsystem.
  Production executable passed API parity, account/storage RPC and GUI checks;
  the controller fixture used real IPv4 and dual-stack IPv6 sockets, checked
  actual owner PID, rejected a foreign executable and adopted the right one.
  This fixes the IPv6 listener invisible in an IPv4-only owner table. Game
  engine/transport ABI did not change. Production symbols retained in CI;
  unhandled master faults write appdata/master/logs/master_crash_*.log.
- Native embedded archive key matched the owner's archive key in memory;
  no key was logged or put into a package as a separate file.
- All 24,939 new archive payloads matched prepared input SHA256 and CRC;
  role aliases and namespace equality verified. Existing base archives retained.
- No game, location server or real world master was started locally. Native
  compilation and executable tests ran only on GitHub. No in-game acceptance.

## Packaged structure and installation

Server candidate has 37 files: `dedicated`, five `resources` archives,
`Start Lost Zone Master.cmd`, `README-server.txt`, `runtime-layout.json` and
`server-release.json`. No top-level bin/client/server/hoster/notices and no
client-specific archive. The native master directly controls map processes.

Client candidate has 138 files (111 archives). Defaults use `$game_config$`
and scripts `$game_scripts$`; customized configs are appdata overrides.
The updater removes old managed files. On first new client startup any residual
client folder is archived under appdata/player/migration, preserving custom
config changes and newer appdata overrides. The running owner's game was
not replaced or launched by this task.

Hoster must stop the previous maps, master and watchdog, then use a separate
new server folder. Copy stopped `appdata` intact. If the old private master
was in hoster/master/runtime, copy that runtime into
appdata/master/legacy-runtime. Native migration preserves identity, keys,
accounts and the SQLite snapshot including committed WAL, verifies integrity,
and retains the original. It does not replace an existing new master database.
Existing map addresses, custom ports and modes are retained. No account reset
or relocation of a character to another map is needed.

The source old standalone builder now requires an explicit legacy flag to
reproduce the retired layout; canonical mode verifies every manifest file,
required native entry, alias digest and absence of private files.

## Delivered server archive

- ZIP: `J:/LostZone_Work/Lost Zone Server.zip`, 2,670,266,962 bytes, 37 entries.
- SHA256: `dfc0cabefb93500633ad0bec5400e7c70365101e9446d986906ac5fedca702f2`.
- Folder: `J:/LostZone_Work/Lost Zone Server`. It was replaced as a whole;
  obsolete bin/client/server/hoster/notices trees cannot survive an overlay.
- Every decompressed ZIP entry matched SHA256; the canonical folder uses
  the exact reviewed file set and independently built production master.
- Rollback source: `_work/server_zip_000047_20261031_084459/previous-folder`.
  The previous public ZIP is retained separately on C: to leave J: headroom.
- The older alias-based ZIP was private staging only, never promoted.
- Intermediate plaintext pack copies were moved to the owner's C: temporary
  folder to free J: space; protected archives and reviewed inputs are retained.

## Publication receipt

- Launcher: `2026.10.31.1`, 138 public files; signed release and BLAKE3
  manifest, all pack bounds/Merkle file hashes verified. New client archives,
  actual executable, filesystem template and startup files reconstructed byte
  for byte from the downloadable packs and compared with the reviewed input.
- Manifest: `manifests/2026.10.31.1-fc18a95c.bin`.
  BLAKE3 `fc18a95c6cd34e9960ec7116a133b3107eece5a10f8ff469ac0ebc79e1a5d61a`.
- New publisher bytes: 2,805,859,292; common archives reused. P2P online after
  publication. Existing publisher reused; no duplicate panel/server started.
- Server ZIP/folder receipts are in `_work/clean_runtime_000047`; production
  master receipt separately pins its own source, run and SHA. No private
  runtime, accounts, database, key, PDB or game data folder was published.
- The owner's running game/native executable was not replaced or started by
  this work. Existing game/user data was not reset.

# 161. Native cluster ownership and clean packages

Owner October 30, after release 000046: existing characters remain stuck at
Yantar, a new account reports the master unavailable, most maps have no port,
the master cannot see running maps. Finish doc 154, redesign master/server
controls, remove hoster/notices/server/client/bin from the **server package**,
remove the loose client folder from the **client package**, remove client patch
archives from the server resources, and make test diagnostics actionable.

No game/location/master is launched locally for testing. Native compilation
and executable fixtures run only in GitHub Actions. Do not alter the owner's
running client. No account/world reset, no silent relocation of characters.

## Confirmed in source

- `Start Locations.cmd` creates the seven-map `.six` plan only when absent,
  then launches hardcoded processes outside the watchdog. The GUI adds all
  33 names, but has no addresses for unplanned maps.
- `AdmissionCoordinator::run` attempts the initial connection only once;
  after failure it stays unavailable until restart. `accounts_take` also
  mislabels this as an unsupported account API, permitting a local fallback.
- Existing bridge/writer credentials are retained by file timestamps and
  can stay stale. An active world-bridge worker never reloads changed config.
- The current GUI launches an external PowerShell watchdog and suppresses
  refresh exceptions. Its process state is not sufficient to diagnose a
  missing authority lease. The location plan and the legacy master runtime
  are not yet migrated to the desired clean structure.

## Implemented and verified for 000047

- Pure `lzm_cluster_plan.h`: complete known maps, preserve custom ports,
  allocate unused UDP pairs for missing rows, collision diagnostics.
- Native bootstrap: `appdata/master/config.json`, SQLite consistent snapshot
  migration from `hoster/master/runtime`, verified integrity, retained legacy
  original; issue all writer/bridge configs from the final credential set.
- `lzm_host.h`: integrated responsive process controller, UDP/PID/executable
  adoption, saved stop commands, persistent modes, serialized memory gate,
  retry quarantine, no forced process kills, local/remote ownership.
- Native master window uses the controller directly; PID and admission
  diagnostics shown. Toolbar rows separated and palette changed.
- Admission retries an initially unavailable authority; no fallback caused by
  transport failure. Phase/status/counters logged and published per map.
- World bridge reopens a failed configuration and reports HTTP/Win32 status.
- Lua config IO bridge in `script_storage.cpp`: io.open/lines/input read
  archived config defaults via a content cache; mutable config overrides live
  in role appdata. Needed before removing the loose config folders.

- Master-owned shared records (stashes/furniture/item state/groups/bans),
  bound and fenced RPC, atomic compare-and-swap, idempotent replay, tombstones,
  legacy import and derived read-only cache. Raw CP1251 values survive RPC.
- Complete engine/Lua A-Life save pairs are checked and chunked into master
  SQLite. The durable pending folder is an outbox, not an independent map
  database. Two verified revisions are retained; startup restores database
  authority, imports legacy files and recovers a damaged pending pair.
- Gateway waits for the exact map, its live PID, current epoch, initialized
  accounts and world data. No alternate-map fallback. The client waits without
  blocking the menu, permits cancellation and reports finite failure states.
- Account readiness is initialized before the first login. Money/auth/role/
  approval updates have independent masks, preventing stale location mirrors
  from undoing operator edits. Online role changes are applied without relogin.
- Stop keeps the master API alive while locations save and exit, pauses the
  launch queue and preserves per-map modes. Existing old-epoch processes are
  asked to save and restart. Conflicting API port reports its owning PID.
- Clean role-specific complete config/script archives mount through native
  aliases. Shared assets are consolidated with every payload SHA256/CRC
  checked: 24,939 files, 2,862,629,814 bytes. No client archives in the server.
- Client startup preserves customized configs and archives the residual old
  client folder under appdata; unchanged defaults use archives. Legacy config
  path aliases are redirected too. Actual native resolver/migration tested.
- Native master has PID/port/state/reason columns, persistent multiselection,
  saved stop, role controls, map log viewer and a bounded diagnostic exporter.
  Actual native GUI screenshots reviewed; all 33 rows have ports after bootstrap.
- Exact engine commit `71cf107cf06e8abace2b6c11624ee3fa45e9a00b` passed DX11
  run `41129739664` and master run `41129910022`. The actual packaged full
  engine renamed `LostZoneMaster.exe` passed bootstrap/window/close in run
  `41172050460`, without any game data or location launch.
- Final server master is its own small production GUI application, built from
  the same master sources without fixture handlers. Source `b63939412`, CI
  `41173412798` includes real IPv4/dual-stack IPv6 process-owner tests and
  production API/GUI checks. Canonical startup no longer loads game code.

Delivery, immutable archive hashes, installation and verification limits are
recorded in [162](162_NATIVE_CLUSTER_RELEASE_000047.md). These changes target
the existing same-host cluster; private API remains loopback. Temporary login
failure counters remain process-local. No multiplayer/in-game acceptance is
claimed, and unrelated old gameplay reports are not declared resolved here.

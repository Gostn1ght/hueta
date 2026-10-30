# 161. Native cluster ownership and clean packages — work in progress

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

## In-progress implementation (not released/tested yet)

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

## Still required before delivery

- Review/fix/fixture all the above. No native build has been dispatched for
  this work yet. Existing 000046 is the last published release.
- Finish authoritative persistence for the remaining doc 154 data, with
  import/restart/transfer fixtures; preserve legacy backups.
- Switch archive packaging to role-specific complete configs/scripts mounted
  through `$game_config$`/`$game_scripts$`, consolidate required shared patch
  assets so removing client-named server archives cannot drop a model/texture.
- Canonical filesystem templates, one native server start entry, licenses in
  dedicated, clean staged server/client builds, launcher stale file cleanup.
- Full meaningful diagnostics: admission/clock/lease/transfer/pickup/trade/
  spawn/state/network summaries and a bounded diagnostic bundle. Never log
  credentials or full private payloads. UI visual verification in CI.
- Successful exact-commit GitHub compilation/fixtures, reviewed staged files,
  publish launcher and verified hoster ZIP together; document actual delivery.

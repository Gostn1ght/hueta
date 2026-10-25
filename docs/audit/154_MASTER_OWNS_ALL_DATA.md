# 154. The master owns all data; one entry port; a clean server folder

Owner, 2026-10-25 (verbatim):

> вероятно из нашей системы акк при переходи не переносится и я думаю у лока
> надо убрать базу данных надо сделать ее полностью мастер серверу и аккаунтов
> и прочей подобной фигни из за которой может сломатся игра, игрок всгде должен
> заходить на порт 5446 например и его будет кидать на сервер с которого он
> выходил и так же у свервера должен быть дедик, и батник запуска а также
> server апдата(база данных игроков алайфа и прочего - мастер сервера) без папки
> serverv, notices,hoster , client и bin(bin - чисто клиент) папкм client у
> клиента тоже не должно быть

## What the location servers keep today (appdata\server)

| Data | File | Problem |
|---|---|---|
| Accounts (login, salt/hash, role, money, approval, lockout) | `netcoop_accounts.txt`, shared by file lock | only maps with the same appdata share it: another folder or machine has no account |
| Characters | `netcoop_character_<login>_<slot>.bin` | same; the master has `native_player_save` but the file is still the source |
| A-Life worlds | `savedgames\*` (236 MB on srvtest) | per folder; the master only leases the writer (`netcoop_world_writer_*.json`) |
| Stashes, furniture, item states | `netcoop_store\` | per folder |
| Bans, cluster secret, login tokens | `netcoop_bans.txt`, `netcoop_cluster.secret`, `netcoop_login.txt` | per folder |
| Caches | `cform_cache`, `xml_cache`, `sound_info.bin`, logs | local, fine |

## Target

- The master (engine `-netcoop_master`, SQLite) is the only store: accounts,
  characters, A-Life worlds of every map, stashes/furniture/item states, bans,
  squads/groups. A location keeps only caches and logs; it reads and writes
  through the master's API and refuses players while the master is away.
- One public entry port, **5446** (`[cluster] entry_port`): the master's
  gateway sends the player to the map he left (new players: the start map). Map
  ports become internal.
- The server folder: `dedicated\` (engine + DLLs + third-party license texts),
  `resources\` (archives), the start file(s), `appdata\` (the master's
  database and caches). No `bin\`, `client\`, `server\`, `hoster\`, `notices\`.
- The client folder: no `client\` (loose configs move into archives).

## Stages

1. **Accounts in the master.** Table `account` (+ migration from every
   `netcoop_accounts.txt` found); location calls: login/register/approve/role/
   money/lockout over the master HTTP API with the cluster secret; the text file
   is read once for migration, then never written.
2. **Characters in the master.** `native_player_save` becomes the only copy;
   the location asks for it on connect and sends it on save/transfer; old
   `.bin` files are imported once.
3. **Entry port 5446** default; the gateway routes by the character's map in the
   master; client and launcher default to it.
4. **A-Life worlds in the master.** The writer lease already exists: the save
   blob goes to the master (chunked, versioned, the last N kept); a map starts
   from the master's copy. `netcoop_store`, bans, groups follow.
5. **No loose configs.** The engine serves Lua `io.open` of game configs from
   the archives (doc 91/96: GAMMA mods read `configs\` with `io.open`), so
   `client\configs` and `server\configs` go into the patch archives.
6. **The master starts the maps.** The watchdog and panel of `hoster\*.ps1`
   move into the master window (it already has the Locations tab); the Python
   master is dropped; one start file `Start Lost Zone Server.cmd`.
7. **Server package without `bin\`**, notices moved into `dedicated\`;
   release scripts and the launcher updated; existing worlds/accounts migrated
   on first start (backup kept).

Each stage: fixtures + parity/selftest in CI, then the owner's check. Nothing
deletes accounts or worlds: migrations copy, the old files stay as backup.

# GAMMA individual recruitment fixture

`individually_recruitable_companions.lua` is the unchanged installed
`individually_recruitable_companions.script` by G_FLAT, normalized from CP1251
to UTF-8 with LF newlines. The original attribution remains in the source.

The item/companion Lua 5.1 check runs its actual free/paid delayed callbacks
through the dedicated ownership wrapper. Clone spawning, timer delivery and
the recruitment/paid-registration leaves are boundary doubles. It checks an
offline recruiter, a different world-queue player, reconnect with a new actor
ID, and callback errors. It does not exercise live NPC pathfinding or server
location migration.

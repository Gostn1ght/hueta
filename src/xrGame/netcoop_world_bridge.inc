// Engine-only adapter; parsing and IO live across a noexcept worker boundary.
// Owner 2026-10-12: the world master is the authority for every location
// server of a cluster - weather, emissions, psi storms and the calendar come
// from it, and a server without it admits no players. An authority bridge
// file (schema 3, written by the panel from the master's config) or a
// cluster plan makes the master required; schema 1/2 files keep the old
// read-only shadow observer.
static netcoop_world::WorldBridgeWorker s_world_shadow_bridge;
static bool s_world_bridge_checked=false, s_world_bridge_active=false;
static u64 s_world_bridge_tick=0, s_world_bridge_log=0, s_world_bridge_retry=0;
static bool s_master_required=false, s_master_ready=false, s_master_was_ready=false;
static netcoop_world::MasterProjection s_master{};
static u64 s_master_wait_log=0, s_master_mono=0;

static bool master_cluster_plan()
{
    string_path config;
    FS.update_path(config,"$app_data_root$","netcoop_cluster.ltx");
    return GetFileAttributesA(config)!=INVALID_FILE_ATTRIBUTES;
}

bool master_required() { return s_master_required; }
bool master_ready() { return s_master_ready; }
// The master's projected game time and scale; false while it is unavailable.
bool master_clock(double& world_ms, double& scale)
{
    if (!s_master_ready) return false;
    // Projected to this moment: a hibernating server runs few frames, and the
    // snapshot taken on one of them is seconds old by the next clock check.
    scale=s_master.world.clock.time_scale;
    world_ms=s_master.estimated_world_ms+double(GetTickCount64()-s_master_mono)*scale;
    return world_ms>0 && scale>0;
}

// For the server Lua (netcoop_master_state): one line - "0" without a master
// (single server), "2" while a required master is unavailable, else
//   1 world_ms scale | weather id source target transition settled |
//   emission id warning ended | psi id warning ended
// (an absent schedule is "-").
LPCSTR script_master_state()
{
    static string2048 text;
    if (!s_master_ready) { xr_strcpy(text,s_master_required ? "2" : "0"); return text; }
    string512 weather="-", emission="-", psi="-";
    const auto& w=s_master.weather;
    if (w.present) xr_sprintf(weather,"%s %s %s %.0f %.0f",w.id,w.source,w.target,w.active,w.ended);
    const auto& e=s_master.emission;
    if (e.present) xr_sprintf(emission,"%s %.0f %.0f",e.id,e.warning,e.ended);
    const auto& p=s_master.psi_storm;
    if (p.present) xr_sprintf(psi,"%s %.0f %.0f",p.id,p.warning,p.ended);
    xr_sprintf(text,"1 %.0f %.4f|%s|%s|%s",s_master.estimated_world_ms,s_master.world.clock.time_scale,weather,emission,psi);
    return text;
}

static void server_world_bridge_update()
{
    if (!g_pGameLevel || !ai().get_alife()) return;
    LPCSTR location=*Level().name();
    if (!location || !location[0]) return;
    const u64 now=GetTickCount64();
    if (s_world_bridge_tick && now-s_world_bridge_tick<1000) return;
    s_world_bridge_tick=now;
    netcoop_world::WorldStateSnapshot local{};
    if (!const_cast<CALifeSimulator*>(ai().get_alife())->time_manager().export_world_state(local)) return;
    // A missing file is looked for again every 10 s: the panel writes it
    // when the master first starts, possibly after this server.
    if(s_world_bridge_active && !s_master_ready && now-s_world_bridge_retry>=30000)
    {
        s_world_shadow_bridge.stop();s_world_bridge_active=false;
        Msg("[diag][world-bridge] map=%s reopening configuration after an unavailable authority",location);
    }
    if (!s_world_bridge_checked || (!s_world_bridge_active && now-s_world_bridge_retry>=10000))
    {
        const bool first=!s_world_bridge_checked;
        s_world_bridge_checked=true; s_world_bridge_retry=now;
        if (first) s_master_required=master_cluster_plan();
        string_path path;
        FS.update_path(path,"$app_data_root$","netcoop_world_bridge.json");
        const int result=s_world_shadow_bridge.start(path,local,location);
        s_world_bridge_active=result==1;
        if (result<0 && first) Msg("! [Lost Zone][master] invalid world master configuration (netcoop_world_bridge.json)");
        if (result==1)
        {
            // The first asynchronous sample is pending, not a connection failure.
            if (first) s_master_wait_log=now;
            // An authority file makes the master required at once, before its first answer.
            IReader* file=FS.r_open(path);
            if (file)
            {
                xr_string body((const char*)file->pointer(), file->length());
                FS.r_close(file);
                if (strstr(body.c_str(),"\"authority\"")) s_master_required=true;
            }
            Msg("[Lost Zone][master] world master configured for map %s%s", location, s_master_required ? " (required)" : "");
        }
    }
    if (!s_world_bridge_active)
    {
        if (s_master_required && (!s_master_wait_log || now-s_master_wait_log>=15000))
        {
            s_master_wait_log=now;
            Msg("! [Lost Zone][master] no world master configuration: start the master from the server panel; players are not admitted");
        }
        return;
    }
    const auto diagnostic=s_world_shadow_bridge.tick(local);
    netcoop_world::MasterProjection projection{};
    const bool have=s_world_shadow_bridge.read_projection(local,projection);
    if (have && projection.authority) s_master_required=true;
    // Only an authority file grants the master its role; a shadow file never does.
    s_master_ready=have && projection.authority;
    if (s_master_ready) { s_master=projection; s_master_mono=now; }
    if (s_master_required && s_master_ready!=s_master_was_ready)
    {
        s_master_was_ready=s_master_ready;
        if (s_master_ready) Msg("[Lost Zone][master] connected to the world master: weather, emissions, psi storms and the calendar follow it");
        else Msg("! [Lost Zone][master] lost the world master: players are not admitted until it is back");
    }
    if (!s_master_ready && s_master_required && (!s_master_wait_log || now-s_master_wait_log>=15000))
    {
        s_master_wait_log=now;
        Msg("! [diag][world-bridge] map=%s api=127.0.0.1:%u ready=%u fetched=%u accepted=%u http=%u win32=%u rtt_ms=%llu; players are not admitted",
            location,diagnostic.api_port,diagnostic.ready,diagnostic.fetched,diagnostic.accepted,diagnostic.http_status,diagnostic.transport_error,diagnostic.rtt_ms);
    }
    if (s_master_required) return; // the diagnostics below are for the read-only shadow observer
    if (!s_world_bridge_log || now-s_world_bridge_log>=10000)
    {
        s_world_bridge_log=now;
        Msg("[world-bridge-shadow] ready=%u fetched=%u accepted=%u rtt_ms=%llu drift_game_ms=%.3f weather_phase=%u weather_blend=%.3f emission_phase=%u master_binding=%u (read only)",
            diagnostic.ready ? 1u:0u,diagnostic.fetched ? 1u:0u,diagnostic.accepted ? 1u:0u,
            diagnostic.rtt_ms,diagnostic.drift_game_ms,diagnostic.weather_phase,diagnostic.weather_blend,
            diagnostic.emission_phase,diagnostic.master_binding ? 1u:0u);
    }
}

void server_world_bridge_stop()
{
    s_world_shadow_bridge.stop(); // Bounded IO, joined thread, no engine callback.
    s_world_bridge_checked=false;s_world_bridge_active=false;s_world_bridge_tick=0;s_world_bridge_log=0;
    s_world_bridge_retry=0;s_master_required=false;s_master_ready=false;s_master_was_ready=false;
    s_master={};s_master_wait_log=0;
}

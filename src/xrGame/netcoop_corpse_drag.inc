// Stock PHCapture runs only on the location authority. Client ragdolls are
// fixed replicas: creating a local joint cannot move their authoritative body.
#include "../xrPhysics/IPHCapture.h"

namespace netcoop
{
struct CorpseDrag
{
    CActor* actor;
    CEntityAlive* body;
    u16 body_id;
    IPHCapture* capture;
};
static xr_map<u16, CorpseDrag> s_corpse_drags;
static CActor* s_drag_client_actor = nullptr;
static bool s_drag_client_active = false;

void corpse_drag_client_state(bool active)
{
    CActor* actor = g_pGameLevel ? smart_cast<CActor*>(Level().CurrentControlEntity()) : nullptr;
    if (s_drag_client_actor == actor && actor && s_drag_client_active && !active)
        actor->HideAllWeapons(false);
    s_drag_client_actor = actor;
    s_drag_client_active = active && actor && actor->g_Alive();
    if (s_drag_client_active) actor->HideAllWeapons(true);
}

bool corpse_drag_use(CActor* actor, CObject* target, u16 bone, bool shift)
{
    if (!pure_client() || !actor || !actor->g_Alive() || actor->netcoop_seated()) return false;
    if (s_drag_client_active && s_drag_client_actor == actor)
    {
        script_command("corpse_drag 65535 65535");
        return true;
    }
    CEntityAlive* body = smart_cast<CEntityAlive*>(target);
    if (!shift || !body || body->g_Alive()) return false;
    string128 command;
    xr_sprintf(command, "corpse_drag %u %u", body->ID(), bone);
    script_command(command);
    return true; // do not also loot the mutant or create a local capture
}

static void corpse_drag_stop(u16 id, const CorpseDrag& drag, LPCSTR reason)
{
    // Object IDs can be reused after a death, disconnect or level change.
    CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(id));
    if (actor == drag.actor && actor->character_physics_support())
    {
        CPHMovementControl* movement = actor->character_physics_support()->movement();
        if (movement && movement->PHCapture() == drag.capture) movement->PHReleaseObject();
        actor->HideAllWeapons(false);
        script_send_to_actor(id, "netcoop_corpse_drag", "0");
    }
    Msg("[diag][corpse_drag] release actor=%u body=%u reason=%s", id, drag.body_id, reason);
}

bool server_corpse_drag_command(xrServer* server, xrClientData* client, LPCSTR text)
{
    if (strncmp(text, "corpse_drag", 11) || (text[11] && text[11] != ' ')) return false;
    if (!server || !client || !client->owner || pure_client() || !g_pGameLevel ||
        !server_character_accepts(client, M_NETANOMALY_CMD)) return true;
    const u16 actor_id = client->owner->ID;
    if (!actor_id) return true;
    auto held = s_corpse_drags.find(actor_id);
    if (held != s_corpse_drags.end())
    {
        corpse_drag_stop(actor_id, held->second, "use");
        s_corpse_drags.erase(held);
        return true;
    }
    CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
    unsigned body_id = 65535, bone = 65535;
    char extra = 0;
    if (sscanf(text + 11, "%u %u %c", &body_id, &bone, &extra) != 2 || body_id >= 65535 || bone >= 65535 ||
        !actor || !actor->g_Alive() || actor->getDestroy() || actor->netcoop_seated() || actor->m_netcoop_noclip)
        return true;
    CEntityAlive* body = smart_cast<CEntityAlive*>(Level().Objects.net_Find(u16(body_id)));
    if (!body || body == actor || body->g_Alive() || body->getDestroy() || body->H_Parent() || !body->PPhysicsShell()) return true;
    CPhysicsShell* shell = body->PPhysicsShell();
    const float mass = shell->getMass();
    if (!shell->isActive() || !_valid(mass) || mass <= 0.f || mass > 300.f) return true;
    for (const auto& entry : s_corpse_drags)
        if (entry.second.body == body) return true;
    CPHMovementControl* movement = actor->character_physics_support() ? actor->character_physics_support()->movement() : nullptr;
    if (!movement || !movement->CharacterExist() || movement->PHCapture()) return true;
    const u16 count = body->PHGetSyncItemsNumber();
    if (!count || count > 128) return true;
    Fvector point;
    bool physical = false;
    for (u16 i = 0; i < count; ++i)
    {
        CPhysicsElement* element = shell->get_ElementByStoreOrder(i);
        if (element->BoneID() != bone) continue;
        SPHNetState state;
        body->PHGetSyncItem(i)->get_State(state);
        point = state.position;
        physical = _valid(point);
        break;
    }
    if (!physical) return true;
    Fvector start = actor->Position();
    start.y += 1.f;
    Fvector direction;
    direction.sub(point, start);
    const float distance = direction.magnitude();
    if (!_valid(distance) || distance > 2.5f) return true;
    if (distance > 0.1f)
    {
        direction.mul(1.f / distance);
        collide::rq_result hit;
        if (Level().ObjectSpace.RayPick(start, direction, distance - 0.05f, collide::rqtStatic, hit, actor)) return true;
    }
    shell->Enable();
    movement->PHCaptureObject(body, u16(bone));
    IPHCapture* capture = movement->PHCapture();
    if (!capture || capture->Failed())
    {
        Msg("! [diag][corpse_drag] stock capture failed actor=%u body=%u bone=%u", actor_id, body_id, bone);
        return true;
    }
    s_corpse_drags[actor_id] = {actor, body, u16(body_id), capture};
    script_send_to_actor(actor_id, "netcoop_corpse_drag", "1");
    Msg("[diag][corpse_drag] capture actor=%u body=%u bone=%u distance=%.2f", actor_id, body_id, bone, distance);
    return true;
}

void server_corpse_drag_update(xrServer* server)
{
    if (!g_pGameLevel || pure_client()) return;
    for (auto it = s_corpse_drags.begin(); it != s_corpse_drags.end();)
    {
        const CorpseDrag& drag = it->second;
        CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(it->first));
        CEntityAlive* body = smart_cast<CEntityAlive*>(Level().Objects.net_Find(drag.body_id));
        bool valid = actor == drag.actor && body == drag.body;
        if (valid)
        {
            CPHMovementControl* movement = actor->character_physics_support() ? actor->character_physics_support()->movement() : nullptr;
            FindActorOwner find; find.actor_id = it->first;
            xrClientData* client = server ? static_cast<xrClientData*>(server->FindClient(find)) : nullptr;
            valid = client && client->flags.bConnected && server_character_accepts(client, M_NETANOMALY_CMD) &&
                actor->g_Alive() && !actor->getDestroy() && !actor->netcoop_seated() && !actor->m_netcoop_noclip &&
                !body->g_Alive() && !body->getDestroy() && !body->H_Parent() && body->PPhysicsShell() &&
                movement && movement->CharacterExist() && movement->PHCapture() == drag.capture && !drag.capture->Failed() &&
                actor->Position().distance_to(body->Position()) < 5.f;
        }
        if (valid) { ++it; continue; }
        corpse_drag_stop(it->first, drag, "invalid, detached or disconnected");
        it = s_corpse_drags.erase(it);
    }
}
} // namespace netcoop

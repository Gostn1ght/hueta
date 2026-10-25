// Server-selected marks, retained for late joiners. No client supplies decal events.
struct CoopMark
{
    u32 sequence, stamp, element;
    u16 object;
    Fvector position, direction;
    float size, rotation;
    shared_str texture;
};
static xr_deque<CoopMark> s_marks;
static xr_map<u32, u32> s_mark_cursor;
static xr_deque<CoopMark> s_pending_marks;
static u32 s_mark_sequence = 0, s_received_mark = 0;

static bool mark_matches_object(const CObject* object, LPCSTR texture)
{
    // Blood may land on static scenery or on an organism/corpse. Dynamic
    // props/fragments cannot bleed, including a reused ID in a late mark.
    return !object || smart_cast<const CEntityAlive*>(object) || !strstr(texture, "wm_blood");
}

void client_marks_reset()
{
    s_pending_marks.clear(); s_received_mark = 0;
}

void marks_reset()
{
    s_marks.clear();
    s_mark_cursor.clear();
    s_pending_marks.clear();
    s_mark_sequence = 0;
    s_received_mark = 0;
}

void replicate_mark(CObject* object, u32 element, const Fvector& position,
    const Fvector& direction, float size, LPCSTR textures)
{
    if (!enabled() || pure_client() || !textures || !*textures || !_valid(position) || !_valid(direction)) return;
    const int count = _GetItemCount(textures);
    if (count <= 0) return;
    string256 texture;
    _GetItem(textures, Random.randI(count), texture);
    if (!mark_matches_object(object, texture)) return;
    CoopMark mark;
    mark.sequence = ++s_mark_sequence; mark.stamp = Level().timeServer();
    mark.object = object ? object->ID() : 0xffff; mark.element = element;
    mark.position = position; mark.direction = direction;
    if (object)
    {
        Fmatrix inverse; inverse.invert(object->XFORM());
        inverse.transform_tiny(mark.position); inverse.transform_dir(mark.direction);
    }
    mark.size = size; mark.rotation = Random.randF(0.f, PI_MUL_2); mark.texture = texture;
    s_marks.push_back(mark);
    while (s_marks.size() > 512) s_marks.pop_front();
}

static void server_marks_update(xrServer* server)
{
    const u32 now = Level().timeServer();
    while (!s_marks.empty() && now - s_marks.front().stamp > 600000) s_marks.pop_front();
    struct SendMarks
    {
        xrServer* server;
        void operator()(IClient* client)
        {
            xrClientData* cl = static_cast<xrClientData*>(client);
            if (cl == server->GetServerClient() || !cl->flags.bConnected || !cl->gamma_snapshot_ready || !cl->owner) return;
            u32& cursor = s_mark_cursor[cl->ID.value()];
            unsigned sent = 0;
            for (const CoopMark& mark : s_marks)
            {
                if (s32(mark.sequence - cursor) <= 0) continue;
                if (!server->HasSendQueueRoom(cl, 64) || sent >= 24) break;
                cursor = mark.sequence;
                if (cl->owner->o_Position.distance_to(mark.position) > 150.f && mark.object == 0xffff) continue;
                NET_Packet p; p.w_begin(M_NETCOOP_MARK);
                p.w_u32(mark.sequence); p.w_u32(mark.stamp); p.w_u16(mark.object); p.w_u32(mark.element);
                p.w_vec3(mark.position); p.w_vec3(mark.direction); p.w_float(mark.size); p.w_float(mark.rotation);
                p.w_stringZ(mark.texture);
                server->SendTo(cl->ID, p, net_flags(TRUE, TRUE));
                ++sent;
            }
        }
    } send = {server};
    server->ForEachClientDo(send);
}

void client_on_mark(NET_Packet& p)
{
    if (!pure_client() || p.r_elapsed() < 47) return;
    CoopMark mark; mark.sequence = p.r_u32(); mark.stamp = p.r_u32();
    mark.object = p.r_u16(); mark.element = p.r_u32();
    p.r_vec3(mark.position); p.r_vec3(mark.direction); mark.size = p.r_float(); mark.rotation = p.r_float();
    string256 texture;
    if (!read_string(p, texture, sizeof(texture)) || !*texture || !_valid(mark.position) || !_valid(mark.direction) ||
        !_valid(mark.size) || !_valid(mark.rotation) || mark.size <= 0.f || mark.size > 2.f ||
        s32(mark.sequence - s_received_mark) <= 0) return;
    s_received_mark = mark.sequence; mark.texture = texture;
    s_pending_marks.push_back(mark);
    while (s_pending_marks.size() > 512) s_pending_marks.pop_front();
}

void client_marks_update()
{
    if (!pure_client() || g_dedicated_server) return;
    const u32 now = snapshot_now();
    unsigned drawn = 0;
    while (!s_pending_marks.empty() && drawn < 24)
    {
        const CoopMark& mark = s_pending_marks.front();
        if (s32(now - mark.stamp) < _max(0, g_netcoop_interp_ms)) break;
        FactoryPtr<IWallMarkArray> array;
        array->AppendMark(mark.texture.c_str());
        if (mark.object == 0xffff)
        {
            if (mark.element < u32(Level().ObjectSpace.GetStaticModel()->get_tris_count()))
                Render->add_StaticWallmark(&*array, mark.position, mark.size,
                    Level().ObjectSpace.GetStaticTris() + mark.element, Level().ObjectSpace.GetStaticVerts(),
                    0.f, false, mark.rotation);
        }
        else if (CObject* object = Level().Objects.net_Find(mark.object))
        {
            if (mark_matches_object(object, mark.texture.c_str()))
            {
                if (IKinematics* bones = object->Visual() ? object->Visual()->dcast_PKinematics() : nullptr)
                {
                    Fvector position = mark.position, direction = mark.direction;
                    object->XFORM().transform_tiny(position); object->XFORM().transform_dir(direction);
                    Render->add_SkeletonWallmark(&object->renderable.xform, bones, &*array, position, direction, mark.size);
                }
            }
        }
        s_pending_marks.pop_front(); ++drawn;
    }
}

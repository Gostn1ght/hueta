// Included inside netcoop namespace. Only the PDA render target is sampled;
// no HUD, desktop, game world, password or menu content is transmitted.
static const u32 pda_width = 256, pda_height = 192, pda_bytes = pda_width * pda_height * 2;
static const u32 pda_chunk = 6000, pda_limit = 120000;
struct PdaFrame
{
    u32 sequence = 0, started = 0, complete = 0, relayed = 0;
    xr_vector<u8> data;
    xr_vector<u8> chunks;
    bool valid = false;
};
static xr_map<u16, PdaFrame> s_pda_server, s_pda_client;

static bool pda_assemble(NET_Packet& packet, PdaFrame& frame)
{
    if (packet.r_elapsed() < 10) return false;
    const u32 sequence = packet.r_u32(), size = packet.r_u32();
    const u16 chunk = packet.r_u16();
    if (!sequence || !size || size > pda_limit || chunk >= (size + pda_chunk - 1) / pda_chunk) return false;
    const u32 offset = chunk * pda_chunk, bytes = _min(pda_chunk, size - offset);
    if (packet.r_elapsed() != bytes) return false;
    if (sequence != frame.sequence)
    {
        if (frame.sequence && s32(sequence - frame.sequence) <= 0) return false;
        const u32 now = real_time_ms();
        if (frame.started && now - frame.started < 240) return false;
        frame.sequence = sequence; frame.started = now; frame.valid = false;
        frame.data.assign(size, 0); frame.chunks.assign((size + pda_chunk - 1) / pda_chunk, 0);
    }
    if (size != frame.data.size() || frame.chunks[chunk]) return false;
    packet.r(&frame.data[offset], bytes); frame.chunks[chunk] = 1;
    for (u8 received : frame.chunks) if (!received) return false;
    frame.complete = real_time_ms();
    return true;
}

static NET_Packet pda_packet(u16 id, const PdaFrame& frame, u32 chunk)
{
    NET_Packet packet;
    packet.w_begin(M_NETCOOP_PDA_SCREEN); packet.w_u16(id);
    packet.w_u32(frame.sequence); packet.w_u32(u32(frame.data.size())); packet.w_u16(u16(chunk));
    const u32 offset = chunk * pda_chunk;
    packet.w(&frame.data[offset], _min(pda_chunk, u32(frame.data.size()) - offset));
    return packet;
}

static u32 s_pda_capture_last = 0, s_pda_capture_sequence = 0, s_pda_capture_crc = 0, s_pda_capture_id = 0xffff, s_pda_capture_unchanged = 0;

void pda_reset()
{
    s_pda_server.clear();
    s_pda_client.clear();
    s_pda_capture_last = 0;
    s_pda_capture_sequence = 0;
    s_pda_capture_crc = 0;
    s_pda_capture_id = 0xffff;
    s_pda_capture_unchanged = 0;
}

void client_capture_pda()
{
    if (!pure_client() || !Actor()) return;
    CPda* device = smart_cast<CPda*>(Actor()->inventory().ActiveItem());
    if (!device || device->IsHidden() || !device->m_PdaEnabled) return;
    const u32 now = real_time_ms();
    if (s_pda_capture_last && now - s_pda_capture_last < 334) return;
    s_pda_capture_last = now;
    xr_vector<u8> pixels(pda_bytes);
    if (!CurrentGameUI()) return;
    const Frect& rect = CurrentGameUI()->GetPdaMenu().m_cursor_box;
    Fvector4 crop; crop.set(rect.left / UI_BASE_WIDTH, rect.top / UI_BASE_HEIGHT,
                           rect.right / UI_BASE_WIDTH, rect.bottom / UI_BASE_HEIGHT);
    if (!Render->CapturePdaPixels(pda_width, pda_height, pixels.data(), crop)) return;
    const u32 crc = crc32(pixels.data(), pda_bytes);
    if (device->ID() == s_pda_capture_id && crc == s_pda_capture_crc && now - s_pda_capture_unchanged < 2000) return;
    if (s_pda_capture_id != device->ID()) Msg("[Lost Zone][PDA] owner frame device=%u", device->ID());
    s_pda_capture_id = device->ID(); s_pda_capture_crc = crc; s_pda_capture_unchanged = now;
    PdaFrame frame; frame.sequence = ++s_pda_capture_sequence;
    frame.data.resize(rtc_csize(pda_bytes));
    frame.data.resize(rtc_compress(frame.data.data(), u32(frame.data.size()), pixels.data(), pda_bytes));
    if (frame.data.size() > pda_limit) return;
    for (u32 chunk = 0; chunk * pda_chunk < frame.data.size(); ++chunk)
    {
        NET_Packet packet = pda_packet(device->ID(), frame, chunk);
        Level().Send(packet, net_flags(TRUE, TRUE));
    }
    // Third person on the owning client uses the same frame as observers.
    device->netcoop_apply_screen(pixels.data(), pda_width, pda_height);
}

void server_on_pda_screen(xrServer* server, xrClientData* client, NET_Packet& packet)
{
    if (!client || client->netcoop_role == role_none || !client->owner || packet.r_elapsed() < 12) return;
    const u16 id = packet.r_u16();
    CPda* device = smart_cast<CPda*>(Level().Objects.net_Find(id));
    CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(client->owner->ID));
    // Client-side PDA slot placement is not reflected by the server inventory.
    // Parent ownership still authenticates the only player allowed to publish.
    if (!device || !actor || !actor->g_Alive() || device->H_Parent() != actor || device->getDestroy()) return;
    const bool first = s_pda_server.find(id) == s_pda_server.end();
    PdaFrame& frame = s_pda_server[id];
    if (!pda_assemble(packet, frame)) return;
    xr_vector<u8> pixels(pda_bytes);
    if (rtc_decompress_safe(pixels.data(), pda_bytes, frame.data.data(), u32(frame.data.size())) != pda_bytes) return;
    frame.valid = true;
    frame.relayed = 0;
    if (first || frame.sequence == 1) Msg("[Lost Zone][PDA] server accepted device=%u sequence=%u", id, frame.sequence);
}

void client_on_pda_screen(NET_Packet& packet)
{
    if (!pure_client() || packet.r_elapsed() < 12) return;
    const u16 id = packet.r_u16();
    CPda* device = smart_cast<CPda*>(Level().Objects.net_Find(id));
    if (!device) return;
    PdaFrame& frame = s_pda_client[id];
    if (!pda_assemble(packet, frame)) return;
    xr_vector<u8> pixels(pda_bytes);
    if (rtc_decompress_safe(pixels.data(), pda_bytes, frame.data.data(), u32(frame.data.size())) != pda_bytes) return;
    device->netcoop_apply_screen(pixels.data(), pda_width, pda_height);
    if (frame.sequence == 1) Msg("[Lost Zone][PDA] observer applied device=%u", id);
}

void pda_forget(u16 id)
{
    s_pda_client.erase(id); s_pda_server.erase(id);
}

static void server_pda_update(xrServer* server)
{
    const u32 now = real_time_ms();
    for (auto it = s_pda_server.begin(); it != s_pda_server.end();)
    {
        CPda* device = smart_cast<CPda*>(Level().Objects.net_Find(it->first));
        if (!device || device->getDestroy()) { it = s_pda_server.erase(it); continue; }
        PdaFrame& frame = it->second;
        if (!frame.valid || (frame.relayed && now - frame.relayed < 1000)) { ++it; continue; }
        frame.relayed = now;
        struct SendScreen
        {
            xrServer* server; CPda* device; PdaFrame* frame;
            void operator()(IClient* client)
            {
                xrClientData* CL = static_cast<xrClientData*>(client);
                if (CL == server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready ||
                    !CL->owner || device->H_Parent() == Level().Objects.net_Find(CL->owner->ID) ||
                    CL->owner->o_Position.distance_to(device->Position()) > 50.f || !server->HasSendQueueRoom(CL, 64)) return;
                for (u32 chunk = 0; chunk * pda_chunk < frame->data.size(); ++chunk)
                {
                    NET_Packet packet = pda_packet(device->ID(), *frame, chunk);
                    server->SendTo(CL->ID, packet, net_flags(TRUE, TRUE));
                }
            }
        } send = {server, device, &frame};
        server->ForEachClientDo(send);
        ++it;
    }
}

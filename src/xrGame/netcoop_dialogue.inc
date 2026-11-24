// Included in netcoop.cpp (namespace netcoop) - dialogues.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// dialogue
// ---------------------------------------------------------------------------
namespace netcoop
{
enum ETalkOp : u8
{
	talk_start = 0,
	talk_choose = 1,
	talk_stop = 2,
	talk_upgrade = 3,
};

enum ETalkFlags : u8
{
	talk_flag_open = 1,
	talk_flag_trade = 2,
	talk_flag_mechanic = 4,
};

static const u32 talk_max_text = 1024;
static const u32 talk_max_entries = 64;
static const float talk_max_distance = 5.f;
static xr_deque<TalkState> s_talk_states;

void client_talk_start(u16 npc_id)
{
	s_talk_states.clear();
	Msg("[Lost Zone] talk request to NPC %u", npc_id);
	NET_Packet P;
	P.w_begin(M_NETCOOP_TALK);
	P.w_u8(talk_start);
	P.w_u16(npc_id);
	Level().Send(P, net_flags(TRUE, TRUE));
}

void client_talk_choose(LPCSTR id)
{
	if (!id || !id[0] || xr_strlen(id) >= 256)
		return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_TALK);
	P.w_u8(talk_choose);
	P.w_stringZ(id);
	Level().Send(P, net_flags(TRUE, TRUE));
}

void client_talk_stop()
{
	if (!g_pGameLevel)
		return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_TALK);
	P.w_u8(talk_stop);
	Level().Send(P, net_flags(TRUE, TRUE));
}

void client_talk_upgrade()
{
	if (!g_pGameLevel)
		return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_TALK);
	P.w_u8(talk_upgrade);
	Level().Send(P, net_flags(TRUE, TRUE));
}

void client_on_talk_state(NET_Packet& P)
{
	if (P.r_elapsed() < 2 + 1 + 2)
		return;
	TalkState state;
	state.npc = P.r_u16();
	const u8 flags = P.r_u8();
	state.open = !!(flags & talk_flag_open);
	state.trade = !!(flags & talk_flag_trade);
	state.mechanic = !!(flags & talk_flag_mechanic);
	Msg("[Lost Zone] talk state from server: NPC %u open=%d trade=%d", state.npc, state.open ? 1 : 0, state.trade ? 1 : 0);

	string1024 text;
	string256 id;
	const u16 lines = P.r_u16();
	for (u16 i = 0; i < lines && i < talk_max_entries; ++i)
	{
		if (P.r_elapsed() < 1)
			return;
		TalkLine line;
		line.npc = !!P.r_u8();
		if (!read_string(P, text, sizeof(text)))
			return;
		line.text = text;
		state.lines.push_back(line);
	}
	if (P.r_elapsed() < 2)
		return;
	const u16 choices = P.r_u16();
	for (u16 i = 0; i < choices && i < talk_max_entries; ++i)
	{
		TalkChoice choice;
		if (!read_string(P, id, sizeof(id)) || !read_string(P, text, sizeof(text)) || P.r_elapsed() < 1)
			return;
		choice.id = id;
		choice.text = text;
		choice.finalizer = !!P.r_u8();
		state.choices.push_back(choice);
	}
	s_talk_states.push_back(state);
}

bool client_take_talk_state(TalkState& out)
{
	if (s_talk_states.empty())
		return false;
	out = s_talk_states.front();
	s_talk_states.pop_front();
	return true;
}

struct TalkSession
{
	u16 npc;
	DIALOG_SHARED_PTR current;
};

typedef xr_map<u32, TalkSession> TalkSessions;
static TalkSessions s_talk_sessions;
static TalkState* s_talk_capture = NULL;

static void capture_line(bool npc, LPCSTR text)
{
	if (!s_talk_capture || !text || !text[0] || s_talk_capture->lines.size() >= talk_max_entries)
		return;
	TalkLine line;
	line.npc = npc;
	line.text = text;
	s_talk_capture->lines.push_back(line);
}

bool talk_capture_answer(LPCSTR text)
{
	if (!s_talk_capture)
		return false;
	capture_line(true, text);
	return true;
}

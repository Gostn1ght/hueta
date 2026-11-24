// Included in netcoop.cpp (namespace netcoop) - PDA news.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// PDA news
// ---------------------------------------------------------------------------
struct FindActorOwner
{
	u16 actor_id;
	bool operator()(IClient* client) const
	{
		xrClientData* CL = static_cast<xrClientData*>(client);
		return CL && !CL->flags.bLocal && CL->owner && CL->owner->ID == actor_id;
	}
};

void server_forward_news(u16 actor_id, const GAME_NEWS_DATA& news)
{
	if (!enabled() || !g_pGameLevel || !Level().Server)
		return;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	if (!CL)
		return;
	const u32 limit = 4000;
	if (news.news_caption.size() > limit || news.news_text.size() > limit || news.texture_name.size() > 256)
		return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_NEWS);
	P.w_u8(u8(news.m_type));
	P.w_stringZ(news.news_caption.size() ? news.news_caption.c_str() : "");
	P.w_stringZ(news.news_text.size() ? news.news_text.c_str() : "");
	P.w_stringZ(news.texture_name.size() ? news.texture_name.c_str() : "");
	P.w_s32(news.show_time);
	if (news.m_type == GAME_NEWS_DATA::eTalk)
	{
		auto* actor = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
		auto* partner = actor ? actor->GetTalkPartner() : nullptr;
		P.w_u16(partner ? partner->object_id() : u16(-1));
	}
	Level().Server->SendTo(CL->ID, P, net_flags(TRUE, TRUE));
}

void server_task_arrived(CActor& actor, CGameTask& task)
{
	GAME_NEWS_DATA news;
	news.m_type = actor.GetTalkPartner() ? GAME_NEWS_DATA::eTalk : GAME_NEWS_DATA::eNews;
	news.news_caption = CStringTable().translate("general_new_task");
	xr_string title = CStringTable().translate(task.GetTitle_script() ? task.GetTitle_script() : "").c_str();
	title += ".";
	news.news_text = title.c_str();
	const LPCSTR icon = task.GetIconName_script();
	news.texture_name = icon && *icon ? icon : "ui_iconsTotal_storyline";
	news.show_time = 10000;
	actor.AddGameNews(news);
	script_send_to_actor(actor.ID(), "task_arrival_sound", "");
}

bool client_present_talk_news(CActor& actor, const GAME_NEWS_DATA& news, u16 npc_id)
{
	if (news.m_type != GAME_NEWS_DATA::eTalk || npc_id == u16(-1))
		return false;
	auto* partner = actor.GetTalkPartner();
	if (!partner || partner->object_id() != npc_id)
		return false;
	auto* ui = smart_cast<CUIGameSP*>(CurrentGameUI());
	if (!ui || !ui->TalkMenu || !ui->TalkMenu->IsShown() || ui->TalkMenu->OthersInvOwner() != partner)
		return false;
	// The dialog inserts its own registry entry. Do not add a second copy.
	ui->TalkMenu->AddIconedMessage(news.news_caption.c_str(), news.news_text.c_str(),
		news.texture_name.size() ? news.texture_name.c_str() : "ui_inGame2_PD_Lider", "iconed_answer_item");
	return true;
}

void client_on_news(NET_Packet& P)
{
	if (!pure_client() || P.r_elapsed() < 1)
		return;
	CActor* actor = smart_cast<CActor*>(Level().CurrentControlEntity());
	if (!actor)
		return;
	GAME_NEWS_DATA news;
	news.m_type = P.r_u8() == GAME_NEWS_DATA::eTalk ? GAME_NEWS_DATA::eTalk : GAME_NEWS_DATA::eNews;
	string4096 caption, text;
	string256 texture;
	if (!read_string(P, caption, sizeof(caption)) || !read_string(P, text, sizeof(text)) ||
		!read_string(P, texture, sizeof(texture)) || P.r_elapsed() < sizeof(s32))
		return;
	news.news_caption = caption;
	news.news_text = text;
	news.texture_name = texture;
	news.show_time = P.r_s32();
	clamp(news.show_time, 0, 60000);
	const u16 npc_id = news.m_type == GAME_NEWS_DATA::eTalk && P.r_elapsed() >= sizeof(u16) ? P.r_u16() : u16(-1);
	if (client_present_talk_news(*actor, news, npc_id))
		return;
	actor->AddGameNews(news);
}

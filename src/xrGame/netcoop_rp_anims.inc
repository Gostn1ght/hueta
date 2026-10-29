// Included in netcoop.cpp (namespace netcoop) - RP animations (player emotes).
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// RP animations (player emotes), configs/netcoop/rp_anims.ltx.
// ---------------------------------------------------------------------------
namespace netcoop
{
static void rp_split(LPCSTR text, xr_vector<shared_str>& out)
{
	out.clear();
	if (!text)
		return;
	const u32 count = _GetItemCount(text);
	string256 item;
	for (u32 i = 0; i < count; ++i)
	{
		_GetItem(text, i, item);
		_Trim(item);
		if (item[0])
			out.push_back(item);
	}
}

const xr_vector<RpAnim>& rp_anims()
{
	static xr_vector<RpAnim> anims;
	static bool loaded = false;
	if (loaded)
		return anims;
	loaded = true;
	string_path path;
	if (!FS.exist(path, "$game_config$", "netcoop\\rp_anims.ltx"))
	{
		Msg("~ [Lost Zone] rp: configs\\netcoop\\rp_anims.ltx not found");
		return anims;
	}
	CInifile ini(path, TRUE, TRUE, FALSE);
	if (!ini.section_exist("rp_list"))
		return anims;
	CInifile::Sect& list = ini.r_section("rp_list");
	for (auto it = list.Data.begin(); it != list.Data.end() && anims.size() < 250; ++it)
	{
		string128 section;
		xr_sprintf(section, "rp_%s", it->first.c_str());
		if (!ini.section_exist(section))
			continue;
		RpAnim a;
		a.name = it->first;
		a.title = ini.line_exist(section, "title") ? ini.r_string(section, "title") : it->first.c_str();
		rp_split(ini.line_exist(section, "in") ? ini.r_string(section, "in") : NULL, a.in);
		rp_split(ini.line_exist(section, "mid") ? ini.r_string(section, "mid") : NULL, a.mid);
		rp_split(ini.line_exist(section, "out") ? ini.r_string(section, "out") : NULL, a.out);
		a.loop = ini.line_exist(section, "loop") ? !!ini.r_bool(section, "loop") : true;
		a.once = ini.line_exist(section, "once") && !!ini.r_bool(section, "once");
		a.walk = ini.line_exist(section, "walk") && !!ini.r_bool(section, "walk");
		rp_split(ini.line_exist(section, "legs") ? ini.r_string(section, "legs") : NULL, a.legs);
		rp_split(ini.line_exist(section, "torso") ? ini.r_string(section, "torso") : NULL, a.torso);
		const int slot = ini.line_exist(section, "slot") ? ini.r_s32(section, "slot") : 0;
		a.slot = u8(slot > 0 && slot < 16 ? slot : 0);
		const LPCSTR weapon = ini.line_exist(section, "weapon") ? ini.r_string(section, "weapon") : "";
		a.weapon = !xr_strcmp(weapon, "pistol") ? 2 : (!xr_strcmp(weapon, "rifle") || a.slot) ? 1 : 0;
		rp_split(ini.line_exist(section, "items") ? ini.r_string(section, "items") : NULL, a.items);
		if (a.walk && (a.legs.size() != 5 || a.torso.size() != 2))
		{
			Msg("! [Lost Zone] rp: %s walks but needs 5 legs and 2 torso motions", section);
			continue;
		}
		anims.push_back(a);
	}
	Msg("[Lost Zone] rp: %u animations", u32(anims.size()));
	return anims;
}

LPCSTR script_rp_list()
{
	static xr_string text;
	text.clear();
	for (const RpAnim& a : rp_anims())
	{
		text += a.name.c_str();
		text += "=";
		text += a.title.c_str();
		text += ";";
	}
	return text.c_str();
}

bool script_rp_play(LPCSTR name)
{
	CActor* actor = Actor();
	if (!actor || !actor->g_Alive() || !name)
		return false;
	const xr_vector<RpAnim>& anims = rp_anims();
	for (u32 i = 0; i < anims.size(); ++i)
	{
		if (!xr_strcmp(anims[i].name, name))
		{
			return actor->rp_start(int(i), true);
		}
	}
	return false;
}

void script_rp_stop()
{
	if (CActor* actor = Actor())
		actor->rp_request_stop(true);
}

LPCSTR script_rp_active()
{
	CActor* actor = Actor();
	if (!actor || actor->m_rp_index < 0 || actor->m_rp_index >= int(rp_anims().size()))
		return "";
	return rp_anims()[actor->m_rp_index].name.c_str();
}
} // namespace netcoop

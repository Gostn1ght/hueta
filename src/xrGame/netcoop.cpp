#include "pch_script.h"
#include "netcoop.h"
#include "netcoop_consumption.h"
#include "../xrSound/SoundVoice.h"
#include "xr_level_controller.h"
#include "ui_defs.h"
#include "../xrEngine/netcoop_menu_camera.h"

#include <bcrypt.h>
#include <algorithm>
#include <io.h>
#include "netcoop_storage_policy.h"
#include <wincrypt.h>
#include <winhttp.h>
#include <windns.h>
#include "../3rd party/nlohmann/json.hpp"
#include "netcoop_world_bridge_worker.h"
#include "netcoop_admission.h"
#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "crypt32.lib")
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "dnsapi.lib")

#include "xrServer.h"
#include "game_sv_base.h"
#include "inventory_space.h"
#include "xrMessages.h"
#include "Level.h"
#include "Level_Bullet_Manager.h"
#include "WeaponAmmo.h"
#include "ParticlesObject.h"
#include "Actor.h"
#include "Actor_Flags.h"
#include "character_community.h"
#include "ui_base.h"
#include "string_table.h"
#include "xr_level_controller.h"
#include "InventoryOwner.h"
#include "Inventory.h"
#include "PDA.h"
#include "InventoryBox.h"
#include "PhysicObject.h"
#include "xrPhysics/IPHWorld.h"
#include "PHCollisionDamageReceiver.h"
#include "PHDestroyable.h"
#include "hit_immunity.h"
#include "Hit.h"
#include "damage_manager.h"
#include "DestroyablePhysicsObject.h"
#include "BreakableObject.h"
#include "PhysicsSkeletonObject.h"
#include "Torch.h"
#include "CustomDevice.h"
#include "ZoneCampfire.h"
#include "alife_simulator.h"
#include "alife_graph_registry.h"
#include "alife_object_registry.h"
#include "alife_time_manager.h"
#include "../xrEngine/Environment.h"
#include "../xrEngine/IGame_Persistent.h"
#include "inventory_item.h"
#include "entity_alive.h"
#include "trade.h"
#include "ai_space.h"
#include "game_graph.h"
#include "level_graph.h"
#include "ai_object_location.h"
#include "Weapon.h"
#include "WeaponAmmo.h"
#include "eatable_item.h"
#include "netcoop_item_state.h"
#include "netcoop_save_checksum.h"
#include "netcoop_prop_mass.h"
#include "Missile.h"
#include "Explosive.h"
#include "script_engine.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "xrServer_Objects_ALife_Items.h"
#include "game_base_space.h"
#include "PhraseDialog.h"
#include "PhraseDialogManager.h"
#include "game_sv_single.h"
#include "GameTaskManager.h"
#include "GameTask.h"
#include "alife_registry_wrappers.h"
#include "UIGameCustom.h"
#include "ui/UIPdaWnd.h"
#include "game_news.h"
#include "../xrPhysics/PhysicsShell.h"
#include "../xrServerEntities/PHSynchronize.h"
#include "../xrEngine/gamemtllib.h"
#include "../Include/xrRender/Kinematics.h"
#include "../Include/xrRender/KinematicsAnimated.h"
#include "../xrEngine/XR_IOConsole.h"
#include "level_changer.h"
#include <time.h>

extern xr_vector<CLevelChanger*> g_lchangers;

// device.cpp: the engine's secondary thread (sampled on server hitches).
extern ENGINE_API HANDLE g_mt_thread_handle;

namespace netcoop
{
// ---------------------------------------------------------------------------
// common helpers
// ---------------------------------------------------------------------------
static const u32 client_key_iterations = 20000;
static const u32 server_hash_iterations = 60000;
static const u32 key_bytes = 32;
static const u32 salt_bytes = 16;
static const float trade_max_distance = 6.f;

bool enabled()
{
	static int state = -1;
	if (state < 0)
		state = strstr(Core.Params, "-netcoop") ? 1 : 0;
	return state == 1;
}

namespace
{
struct ClientMapPosition
{
	Fvector position;
	shared_str level;
};
xr_map<u16, ClientMapPosition> s_client_map_positions;
}

void client_map_position_set(u16 id, const Fvector& position, LPCSTR level)
{
	ClientMapPosition& entry = s_client_map_positions[id];
	entry.position = position;
	entry.level = level && level[0] ? level : (g_pGameLevel ? *Level().name() : "");
}

void client_map_position_clear(u16 id) { s_client_map_positions.erase(id); }

void client_map_positions_reset() { s_client_map_positions.clear(); }

bool client_map_position(u16 id, Fvector& position, shared_str& level)
{
	const auto found = s_client_map_positions.find(id);
	if (found == s_client_map_positions.end()) return false;
	position = found->second.position;
	level = found->second.level;
	return true;
}

bool corpse_loot_drops()
{
	static int state = -1;
	if (state < 0)
		state = strstr(Core.Params, "-netcoop_corpse_drop") ? 1 : 0;
	return state == 1;
}

bool pure_client()
{
	return enabled() && g_pGameLevel && !Level().Server;
}

LPCSTR role_name(u8 role)
{
	switch (role)
	{
	case role_admin: return "admin";
	case role_player: return "player";
	default: return "none";
	}
}

bool read_string(NET_Packet& P, LPSTR dest, u32 dest_size)
{
	dest[0] = 0;
	if (P.r_pos >= P.B.count)
		return false;
	const u8* start = P.B.data + P.r_pos;
	const u32 available = P.B.count - P.r_pos;
	const void* end = memchr(start, 0, available);
	if (!end)
		return false;
	const u32 length = u32((const u8*)end - start);
	if (length + 1 > dest_size)
		return false;
	CopyMemory(dest, start, length + 1);
	P.r_pos += length + 1;
	return true;
}

static void to_lower(xr_string& s)
{
	for (u32 i = 0; i < s.size(); ++i)
		s[i] = (char)tolower((unsigned char)s[i]);
}

static bool login_valid(LPCSTR login)
{
	const u32 n = xr_strlen(login);
	if (n < 3 || n > 20)
		return false;
	for (u32 i = 0; i < n; ++i)
	{
		const char c = login[i];
		if (!isalnum((unsigned char)c) && c != '_' && c != '-' && c != '.')
			return false;
	}
	return true;
}

static bool key_valid(LPCSTR key)
{
	if (xr_strlen(key) != key_bytes * 2)
		return false;
	for (LPCSTR c = key; *c; ++c)
	{
		if (!((*c >= '0' && *c <= '9') || (*c >= 'a' && *c <= 'f')))
			return false;
	}
	return true;
}

static xr_string to_hex(const u8* data, u32 size)
{
	static const char digits[] = "0123456789abcdef";
	xr_string out;
	out.resize(size * 2);
	for (u32 i = 0; i < size; ++i)
	{
		out[i * 2] = digits[data[i] >> 4];
		out[i * 2 + 1] = digits[data[i] & 15];
	}
	return out;
}

static bool pbkdf2(const void* secret, u32 secret_size, const void* salt, u32 salt_size, u32 iterations, u8* out,
                   u32 out_size)
{
	BCRYPT_ALG_HANDLE alg = NULL;
	if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG)))
		return false;
	const NTSTATUS status = BCryptDeriveKeyPBKDF2(alg, (PUCHAR)secret, secret_size, (PUCHAR)salt, salt_size,
	                                              iterations, out, out_size, 0);
	BCryptCloseAlgorithmProvider(alg, 0);
	return BCRYPT_SUCCESS(status);
}

static bool random_bytes(u8* out, u32 size)
{
	return BCRYPT_SUCCESS(BCryptGenRandom(NULL, out, size, BCRYPT_USE_SYSTEM_PREFERRED_RNG));
}

static bool constant_time_equal(const xr_string& a, const xr_string& b)
{
	if (a.size() != b.size())
		return false;
	u8 diff = 0;
	for (u32 i = 0; i < a.size(); ++i)
		diff |= u8(a[i] ^ b[i]);
	return diff == 0;
}

static void call_lua(LPCSTR function, bool ok, u8 role, LPCSTR message)
{
	::luabind::functor<void> f;
	if (ai().script_engine().functor(function, f))
	{
		try
		{
			f(ok, int(role), message);
		}
		catch (...)
		{
			Msg("! [Lost Zone] %s failed", function);
		}
	}
}

#include "netcoop_client.inc"
#include "netcoop_accounts.inc"
#include "netcoop_auth.inc"
#include "netcoop_events.inc"
#include "netcoop_trade.inc"
#include "netcoop_dialogue.inc"
#include "netcoop_tasks.inc"
#include "netcoop_task_list.inc"
#include "netcoop_task_list_client.inc"
#include "netcoop_news.inc"
#include "netcoop_script_messages.inc"
#include "netcoop_net_sync.inc"
#include "netcoop_rp_anims.inc"

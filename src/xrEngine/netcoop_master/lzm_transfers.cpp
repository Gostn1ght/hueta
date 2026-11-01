#include "lzm_ownership.h"

#include <set>

namespace lzm
{
static const json& arg(const json& args, const char* name)
{
    static const json none;
    auto it = args.find(name);
    return it == args.end() ? none : *it;
}

static const json& field(const json& object, const char* name)
{
    auto it = object.find(name);
    if (it == object.end()) throw Invalid("invalid transfer token");
    return *it;
}

// -- transfers.py -------------------------------------------------------------------------------------
Transfers::Transfers(World& world, Ownership& ownership, const std::string& signing_key)
    : world_(world), store_(world.store), ownership_(ownership), key_(signing_key)
{
    if (key_.size() < 32) throw Invalid("transfer signing key must contain at least 32 bytes");
    if (!world.lease_renew_hooks.count("ExpireUnclaimedTransfers"))
        world.lease_renew_hooks["ExpireUnclaimedTransfers"] = [this](Db& tx, const std::string& actor, const std::string& location, int64_t fence) {
            expire_unclaimed(tx, actor, location, fence);
        };
}

std::string Transfers::checkpoint_in(Db& tx, const std::vector<std::string>& ids)
{
    json capture = { { "entities", json::array() }, { "items", json::array() }, { "ids", ids } };
    size_t used = canonical(capture, checkpoint_limit_).size();
    auto admit = [&](const char* kind, const json& row) {
        if (row.is_null()) throw Conflict("transfer capture entity disappeared");
        used += canonical(row, checkpoint_limit_).size() + (capture[kind].empty() ? 0 : 1);
        if (used > checkpoint_limit_) throw Invalid("transfer checkpoint exceeds admission byte budget");
        capture[kind].push_back(row);
    };
    for (auto& id : ids) admit("entities", tx.one("SELECT * FROM entity WHERE id=?", { id }));
    for (auto& id : ids)
        for (auto& row : tx.all("SELECT * FROM item WHERE holder=? AND kind IN('PLAYER','NPC','CORPSE') ORDER BY id", { id }))
            admit("items", row);
    return canonical(capture, checkpoint_limit_);
}

std::string Transfers::sign(const json& claims)
{
    std::string encoded = base64_urlsafe_nopad(canonical(claims));
    return encoded + "." + hmac_sha256_hex(key_, encoded);
}

json Transfers::verify(const json& token_value)
{
    if (!token_value.is_string() || token_value.get<std::string>().size() > 2048) throw Invalid("invalid transfer token");
    const std::string& token = token_value.get_ref<const std::string&>();
    auto parts = split(token, '.');
    if (parts.size() != 2) throw Invalid("invalid transfer token");
    for (unsigned char c : parts[0])
        if (c >= 0x80) throw Invalid("invalid transfer token");
    if (!constant_time_equal(parts[1], hmac_sha256_hex(key_, parts[0]))) throw Invalid("invalid transfer signature");
    std::string padded = parts[0] + std::string((4 - parts[0].size() % 4) % 4, '=');
    std::string raw;
    if (!base64_decode(padded, raw, true)) throw Invalid("invalid transfer token");
    json claims;
    try { claims = loads(raw); }
    catch (const Invalid&) { throw Invalid("invalid transfer token"); }
    if (!claims.is_object() || !claims.contains("world_id") || claims["world_id"] != json(world_.world_id) ||
        !claims.contains("audience") || claims["audience"] != "lostzone-transfer-v1")
        throw Invalid("transfer token belongs to another world/audience");
    persistent_id(field(claims, "transfer_id"));
    persistent_id(field(claims, "entity_id"));
    identifier(field(claims, "target"));
    positive(field(claims, "expires_ms"), "token expiry");
    return claims;
}

json Transfers::prepare(const std::string& actor, const std::string& command_id, const json& args)
{
    const json &entity_id = arg(args, "entity_id"), &source_value = arg(args, "source"), &source_fence_value = arg(args, "source_fence"),
               &target_value = arg(args, "target"), &entity_version = arg(args, "entity_version"), &ttl = arg(args, "ttl_ms");
    std::string id = persistent_id(entity_id);
    std::string source = identifier(source_value), target = identifier(target_value);
    int64_t source_fence = positive(source_fence_value, "source fence");
    positive(entity_version);
    if (source == target || !ttl.is_number_integer() || as_int(ttl) < 1000 || as_int(ttl) > 300000)
        throw Invalid("invalid transfer destination/duration");
    json payload = { { "type", "transfer_prepare" }, { "entity_id", entity_id }, { "source", source_value },
                     { "source_fence", source_fence_value }, { "target", target_value }, { "entity_version", entity_version }, { "ttl_ms", ttl } };
    return store_.command(actor, command_id, payload, [&](Db& tx) -> json {
        json root = ownership_.require_entity(tx, actor, entity_id, source_fence_value, entity_version, true);
        std::string kind = root["kind"].get<std::string>();
        if (root["location"] != source || (kind != "CHARACTER" && kind != "NPC" && kind != "MUTANT" && kind != "GROUP"))
            throw Conflict("entity cannot depart this source");
        if ((kind == "NPC" || kind == "MUTANT") && !tx.one("SELECT 1 FROM group_member WHERE member_id=?", { id }).is_null())
            throw Conflict("transfer the persistent group instead of one member");
        json lease = tx.one("SELECT * FROM location_lease WHERE location=?", { target });
        if (lease.is_null() || lease["expires_ms"].get<int64_t>() <= world_.real_ms()) throw Conflict("target authority is unavailable");
        if (kind == "CHARACTER")
        {
            if (!tx.one("SELECT 1 FROM native_player_upload WHERE character_id=?", { id }).is_null())
                throw Conflict("native player checkpoint must finish before handoff");
            json session = tx.one("SELECT * FROM player_session WHERE character_id=?", { id });
            if (session.is_null() || session["state"] != "ACTIVE" || session["owner"] != actor) throw Conflict("character has no active source session");
            ownership_.admission(tx, target, std::nullopt, id);
        }
        std::vector<std::string> ids = { id };
        if (kind == "GROUP")
        {
            json state = loads(root["state"].get<std::string>());
            json members = state.contains("member_ids") ? state["member_ids"] : json::array();
            std::set<std::string> seen;
            bool unique = members.is_array();
            if (unique)
                for (auto& m : members) unique = unique && seen.insert(m.dump()).second;
            if (!members.is_array() || members.size() > 512 || !unique) throw Invalid("invalid persistent group membership");
            for (auto& member : members)
            {
                std::string mid = persistent_id(member);
                json row = tx.one("SELECT id,kind,alive,writer,fence,location FROM entity WHERE id=?", { mid });
                if (row.is_null() || mid == id || (row["kind"] != "NPC" && row["kind"] != "MUTANT")) throw Conflict("invalid persistent group member");
                if (!row["alive"].get<int64_t>()) continue;
                if (row["writer"] != actor || row["fence"].get<int64_t>() != source_fence) throw Conflict("entity writer/fence mismatch");
                if (row["location"] != source) throw Conflict("group member is not owned by source");
                ids.push_back(mid);
            }
            if (ids.size() == 1) throw Conflict("group has no living members to transfer");
        }
        std::string encoded_checkpoint = checkpoint_in(tx, ids);
        std::string transfer_id = uuid4_hex();
        int64_t expiry = world_.real_ms() + as_int(ttl);
        json claims = { { "audience", "lostzone-transfer-v1" }, { "world_id", world_.world_id }, { "transfer_id", transfer_id },
                        { "entity_id", id }, { "target", target }, { "expires_ms", expiry }, { "nonce", token_hex(16) } };
        std::string token = sign(claims);
        tx.exec("INSERT INTO transfer VALUES(?,?,?,?,?,?,NULL,NULL,'PREPARED',?,?,?,?,?)",
                { transfer_id, id, source, target, actor, source_fence, expiry, sha256_hex(token), encoded_checkpoint,
                  entity_version, *store_.epoch });
        for (auto& value : ids) tx.exec("UPDATE entity SET writer=?,version=version+1 WHERE id=?", { "transfer:" + transfer_id, value });
        tx.exec("UPDATE player_session SET owner=?,state='FROZEN',fence=fence+1 WHERE character_id=?", { "transfer:" + transfer_id, id });
        tx.exec("UPDATE character SET session_fence=session_fence+1 WHERE id=?", { id });
        json event_payload = payload;
        event_payload["id"] = transfer_id;
        event_payload["checkpoint_hash"] = sha256_hex(encoded_checkpoint);
        int64_t event = store_.event(tx, "transfer:" + transfer_id, "TransferPrepared", event_payload, world_.now());
        return { { "transfer_id", transfer_id }, { "state", "PREPARED" }, { "token", token }, { "expires_ms", expiry }, { "event", event } };
    }, [&](Db& tx) { world_.require_location(tx, actor, source, source_fence); });
}

json Transfers::claim(const std::string& actor, const std::string& command_id, const json& args)
{
    const json &token = arg(args, "token"), &target_fence_value = arg(args, "target_fence");
    int64_t target_fence = positive(target_fence_value, "target fence");
    json claims = verify(token);
    std::string token_hash = sha256_hex(token.get<std::string>());
    json payload = { { "type", "transfer_claim" }, { "token_hash", token_hash }, { "target_fence", target_fence_value } };
    std::string transfer_id = claims["transfer_id"].get<std::string>();
    return store_.command(actor, command_id, payload, [&](Db& tx) -> json {
        json row = tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id });
        if (row.is_null() || row["token_hash"] != token_hash || row["entity_id"] != claims["entity_id"] || row["target"] != claims["target"])
            throw Conflict("transfer token does not match durable record");
        world_.require_location(tx, actor, row["target"].get<std::string>(), target_fence);
        std::string state = row["state"].get<std::string>();
        if (state == "ABORTED") throw Conflict("transfer was aborted");
        bool mine = row["target_owner"] == actor && row["target_fence"].is_number_integer() && row["target_fence"].get<int64_t>() == target_fence;
        if (state == "COMMITTED")
        {
            if (!mine) throw Conflict("committed transfer belongs to another destination fence");
            return public_view(tx, row);
        }
        if (state == "PREPARED" && row["expires_ms"].get<int64_t>() <= world_.real_ms()) throw Conflict("unclaimed transfer expired");
        if (state == "CLAIMED" && mine) return public_view(tx, row, true);
        tx.exec("UPDATE transfer SET state='CLAIMED',target_owner=?,target_fence=? WHERE id=?", { actor, target_fence, transfer_id });
        store_.event(tx, "transfer:" + transfer_id, "TransferClaimed", { { "target_owner", actor }, { "target_fence", target_fence_value } }, world_.now());
        return public_view(tx, tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id }), true);
    }, [&](Db& tx) { world_.require_location(tx, actor, claims["target"].get<std::string>(), target_fence); });
}

json Transfers::commit(const std::string& actor, const std::string& command_id, const json& args)
{
    const json &transfer_id_value = arg(args, "transfer_id"), &target_fence_value = arg(args, "target_fence");
    std::string transfer_id = persistent_id(transfer_id_value);
    int64_t target_fence = positive(target_fence_value, "target fence");
    json payload = { { "type", "transfer_commit" }, { "id", transfer_id_value }, { "target_fence", target_fence_value } };
    return store_.command(actor, command_id, payload, [&](Db& tx) -> json {
        json row = tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id });
        if (row.is_null() || row["target_owner"] != actor || !row["target_fence"].is_number_integer() || row["target_fence"].get<int64_t>() != target_fence)
            throw Conflict("destination claim/fence mismatch");
        world_.require_location(tx, actor, row["target"].get<std::string>(), target_fence);
        if (row["state"] == "COMMITTED") return public_view(tx, row);
        if (row["state"] != "CLAIMED") throw Conflict("transfer is not claimed");
        json checkpoint = loads(row["checkpoint"].get<std::string>());
        std::string entity = row["entity_id"].get<std::string>();
        json root = tx.one("SELECT kind FROM entity WHERE id=?", { entity });
        if (root["kind"] == "CHARACTER") ownership_.admission(tx, row["target"].get<std::string>(), std::nullopt, entity);
        for (auto& value : checkpoint["ids"])
            if (tx.exec("UPDATE entity SET location=?,writer=?,fence=?,version=version+1 WHERE id=? AND writer=?",
                        { row["target"], actor, target_fence, value, "transfer:" + transfer_id }) != 1)
                throw Conflict("transfer entity ownership changed");
        tx.exec("UPDATE player_session SET owner=?,state='ACTIVE',fence=fence+1 WHERE character_id=? AND state='FROZEN'", { actor, entity });
        tx.exec("UPDATE character SET session_fence=session_fence+1 WHERE id=?", { entity });
        tx.exec("UPDATE transfer SET state='COMMITTED' WHERE id=?", { transfer_id });
        store_.event(tx, "transfer:" + transfer_id, "TransferCommitted",
                     { { "entity_id", entity }, { "source", row["source"] }, { "target", row["target"] }, { "owner", actor },
                       { "fence", target_fence_value }, { "member_ids", checkpoint["ids"] } }, world_.now());
        return public_view(tx, tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id }));
    }, [&](Db& tx) {
        json row = tx.one("SELECT target FROM transfer WHERE id=?", { transfer_id });
        if (row.is_null()) throw Conflict("unknown transfer");
        world_.require_location(tx, actor, row["target"].get<std::string>(), target_fence);
    });
}

json Transfers::abort(const std::string& actor, const std::string& command_id, const json& args)
{
    const json &transfer_id_value = arg(args, "transfer_id"), &source_fence_value = arg(args, "source_fence");
    std::string transfer_id = persistent_id(transfer_id_value);
    int64_t source_fence = positive(source_fence_value, "source fence");
    json payload = { { "type", "transfer_abort" }, { "id", transfer_id_value }, { "source_fence", source_fence_value } };
    return store_.command(actor, command_id, payload, [&](Db& tx) -> json {
        json row = tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id });
        if (row.is_null()) throw Conflict("unknown transfer");
        world_.require_location(tx, actor, row["source"].get<std::string>(), source_fence);
        if (row["state"] == "ABORTED") return public_view(tx, row);
        if (row["state"] != "PREPARED") throw Conflict("claimed/committed transfer requires destination recovery, not source resume");
        return abort_in(tx, row, actor, source_fence, payload);
    }, [&](Db& tx) {
        json row = tx.one("SELECT source FROM transfer WHERE id=?", { transfer_id });
        if (row.is_null()) throw Conflict("unknown transfer");
        world_.require_location(tx, actor, row["source"].get<std::string>(), source_fence);
    });
}

void Transfers::expire_unclaimed(Db& tx, const std::string& actor, const std::string& location, int64_t fence)
{
    auto rows = tx.all("SELECT * FROM transfer WHERE source=? AND state='PREPARED' AND expires_ms<=? ORDER BY expires_ms LIMIT 16",
                       { location, world_.real_ms() });
    for (auto& row : rows)
        abort_in(tx, row, actor, fence, { { "type", "transfer_expire" }, { "id", row["id"] }, { "source_fence", fence } });
}

json Transfers::abort_in(Db& tx, const json& row, const std::string& actor, int64_t source_fence, const json& payload)
{
    std::string transfer_id = row["id"].get<std::string>();
    std::string entity = row["entity_id"].get<std::string>();
    json root = tx.one("SELECT kind FROM entity WHERE id=?", { entity });
    std::string session_state = "ACTIVE";
    if (root["kind"] == "CHARACTER")
    {
        try
        {
            ownership_.admission(tx, row["source"].get<std::string>(), std::nullopt, entity);
        }
        catch (const Conflict&)
        {
            session_state = "DISCONNECTED";
        }
    }
    json checkpoint = loads(row["checkpoint"].get<std::string>());
    for (auto& value : checkpoint["ids"])
        if (tx.exec("UPDATE entity SET writer=?,fence=?,version=version+1 WHERE id=? AND writer=?",
                    { actor, source_fence, value, "transfer:" + transfer_id }) != 1)
            throw Conflict("transfer entity ownership changed");
    tx.exec("UPDATE player_session SET owner=?,state=?,fence=fence+1 WHERE character_id=? AND state='FROZEN'", { actor, session_state, entity });
    tx.exec("UPDATE character SET session_fence=session_fence+1 WHERE id=?", { entity });
    tx.exec("UPDATE transfer SET state='ABORTED' WHERE id=?", { transfer_id });
    store_.event(tx, "transfer:" + transfer_id, "TransferAborted", payload, world_.now());
    return public_view(tx, tx.one("SELECT * FROM transfer WHERE id=?", { transfer_id }));
}

json Transfers::status(const std::string& actor, const json& transfer_id_value)
{
    std::string transfer_id = persistent_id(transfer_id_value);
    std::lock_guard<std::recursive_mutex> guard(store_.lock);
    store_.require_epoch(store_.db);
    json row = store_.db.one("SELECT * FROM transfer WHERE id=?", { transfer_id });
    if (row.is_null()) throw Invalid("unknown transfer");
    auto owners = store_.db.all("SELECT owner FROM location_lease WHERE location IN (?,?)", { row["source"], row["target"] });
    bool allowed = false;
    for (auto& o : owners) allowed = allowed || o["owner"] == actor;
    if (!allowed) throw Conflict("transfer status is restricted to source/destination");
    return public_view(store_.db, row);
}

json Transfers::public_view(Db& tx, const json& row, bool checkpoint)
{
    json result = json::object();
    for (const char* key : { "id", "entity_id", "source", "target", "state", "target_owner", "target_fence", "expires_ms" }) result[key] = row[key];
    if (checkpoint) result["checkpoint"] = loads(row["checkpoint"].get<std::string>());
    json session = tx.one("SELECT state,fence FROM player_session WHERE character_id=?", { row["entity_id"] });
    result["session_state"] = session.is_null() ? json() : session["state"];
    result["session_fence"] = session.is_null() ? json() : session["fence"];
    return result;
}

// -- native_save.py ------------------------------------------------------------------------------------------------
namespace
{
uint32_t crc32c(const std::string& data)
{
    static uint32_t table[256];
    static bool ready = false;
    if (!ready)
    {
        for (uint32_t v = 0; v < 256; ++v)
        {
            uint32_t c = v;
            for (int k = 0; k < 8; ++k) c = (c >> 1) ^ ((c & 1) ? 0x82f63b78U : 0U);
            table[v] = c;
        }
        ready = true;
    }
    uint32_t crc = 0xffffffffU;  // native SSE4.2: no final XOR
    for (unsigned char b : data) crc = (crc >> 8) ^ table[(crc ^ b) & 255];
    return crc;
}

uint32_t zlib_crc32(const std::string& data)
{
    static uint32_t table[256];
    static bool ready = false;
    if (!ready)
    {
        for (uint32_t v = 0; v < 256; ++v)
        {
            uint32_t c = v;
            for (int k = 0; k < 8; ++k) c = (c >> 1) ^ ((c & 1) ? 0xEDB88320U : 0U);
            table[v] = c;
        }
        ready = true;
    }
    uint32_t crc = 0xffffffffU;
    for (unsigned char b : data) crc = (crc >> 8) ^ table[(crc ^ b) & 255];
    return crc ^ 0xffffffffU;
}

constexpr size_t PACKET_LIMIT = 16 * 1024;

struct Reader
{
    const std::string& data;
    int version;
    size_t offset = 4;
    std::string take(size_t size)
    {
        if (size > data.size() - offset) throw Invalid("truncated native player save");
        std::string out = data.substr(offset, size);
        offset += size;
        return out;
    }
    uint32_t u32() { std::string b = take(4); return uint8_t(b[0]) | (uint8_t(b[1]) << 8) | (uint8_t(b[2]) << 16) | (uint32_t(uint8_t(b[3])) << 24); }
    uint16_t u16() { std::string b = take(2); return uint16_t(uint8_t(b[0]) | (uint8_t(b[1]) << 8)); }
    uint8_t u8() { return uint8_t(take(1)[0]); }
    std::string text(size_t limit)
    {
        size_t end = data.find('\0', offset);
        if (end == std::string::npos || end > offset + limit) throw Invalid("unterminated native save string");
        std::string raw = take(end - offset);
        take(1);
        return raw;
    }
    std::string packet(size_t limit)
    {
        uint32_t size = u32(), expected = u32();
        if (size > limit) throw Invalid("native save packet exceeds format bounds");
        std::string d = take(size);
        if (crc32c(d) != expected && !(version < 8 && zlib_crc32(d) == expected)) throw Invalid("native save checksum mismatch");
        return d;
    }
    size_t items()
    {
        uint32_t count = u32();
        if (count > 512) throw Invalid("native save item count exceeds format bounds");
        for (uint32_t index = 0; index < count; ++index)
        {
            if (text(128).empty()) throw Invalid("empty native item section");
            if (u16() > index) throw Invalid("native item parent is forward or cyclic");
            if (version >= 4) u16();
            packet(PACKET_LIMIT);
            if (version >= 7)
            {
                uint16_t size = u16();
                if (size > 512) throw Invalid("native item state exceeds format bounds");
                take(size);
            }
        }
        return count;
    }
};
} // namespace

json NativeSave::summary() const
{
    json result = { { "format", version==10 ? "NCHA":"NCH" + std::to_string(version) }, { "sha256", sha256 }, { "bytes", bytes }, { "items", items },
                    { "safe_items", safe_items }, { "actor_bytes", actor_bytes }, { "progress_bytes", progress_bytes } };
    if (version >= 9) result["inventory_cells"] = inventory_cells;
    if (version >= 10) result["lives_remaining"] = lives_remaining;
    return result;
}

NativeSave parse_native_save(const std::string& data)
{
    if (data.size() < 4 || int64_t(data.size()) > NATIVE_FILE_LIMIT) throw Invalid("native player save exceeds admission bounds");
    if (data.compare(0, 3, "NCH") != 0 || !((data[3]>='3' && data[3]<='9') || data[3]=='A')) throw Invalid("unsupported native player save format");
    NativeSave save;
    save.version = data[3]=='A' ? 10:data[3] - '0';
    Reader reader{ data, save.version };
    std::string name = reader.text(63);
    if (name.empty()) throw Invalid("invalid native character name");
    for (unsigned char c : name)
        if (c < 32 || c == '|') throw Invalid("invalid native character name");
    reader.text(32);
    reader.text(4096);
    if (save.version >= 5)
    {
        reader.text(512);
        reader.text(1536);
    }
    reader.u8();
    uint8_t a = reader.u8();
    uint8_t b = reader.u8();
    if (a > 1 || b > 1) throw Invalid("invalid native player flags");
    save.actor_bytes = int64_t(reader.packet(PACKET_LIMIT).size());
    save.items = int64_t(reader.items());
    save.progress_bytes = save.version >= 4 ? int64_t(reader.packet(1024 * 1024).size()) : 0;
    if (save.version >= 6)
    {
        if (reader.u32() == 0) throw Invalid("invalid native storage revision");
        reader.text(32);
        reader.text(80);
        save.safe_items = int64_t(reader.items());
    }
    save.inventory_cells = save.version >= 9 ? reader.u32() : 0;
    if (save.inventory_cells > 512) throw Invalid("native inventory capacity exceeds format bounds");
    save.lives_remaining=save.version>=10 ? reader.u8():(b ? 4:5);
    if(save.lives_remaining>5)throw Invalid("native lives counter exceeds format bounds");
    if (reader.offset != data.size()) throw Invalid("native player save has trailing data");
    save.sha256 = sha256_hex(data);
    save.bytes = int64_t(data.size());
    return save;
}

std::string native_identity(uint64_t world_id, uint64_t seed, const std::string& account, int64_t slot)
{
    if (world_id == 0) throw Invalid("explicit WorldID and seed are required");
    bool ok = account.size() >= 3 && account.size() <= 20;
    for (unsigned char c : account) ok = ok && (isalnum(c) || c == '_' || c == '.' || c == '-') && c < 0x80;
    if (!ok) throw Invalid("invalid native account identity");
    if (slot < 1 || slot > 10) throw Invalid("invalid native character slot");
    return uuid5_url_hex("lostzone:native-player:" + std::to_string(world_id) + ":" + std::to_string(seed) + ":" + lower(account) + ":" + std::to_string(slot));
}
} // namespace lzm

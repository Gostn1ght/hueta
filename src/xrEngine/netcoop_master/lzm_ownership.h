// ownership.py, transfers.py, player_saves.py (+ native_save.py): the entity
// registry with its item ledger, cross-location handoffs and the players'
// native checkpoints.
#pragma once
#include "lzm_timelines.h"

namespace lzm
{
class Ownership
{
public:
    explicit Ownership(World& world);
    World& world;
    Store& store;

    json create_entity(const std::string& actor, const std::string& command_id, const json& args);
    json update_entity(const std::string& actor, const std::string& command_id, const json& args);
    json disconnect(const std::string& actor, const std::string& command_id, const json& args);
    json resume(const std::string& actor, const std::string& command_id, const json& args);
    json recover_location(const std::string& actor, const std::string& command_id, const json& args);
    json create_item(const std::string& actor, const std::string& command_id, const json& args);
    json move_item(const std::string& actor, const std::string& command_id, const json& args);
    json kill(const std::string& actor, const std::string& command_id, const json& args);
    json cleanup_corpse(const std::string& actor, const std::string& command_id, const json& args);
    json location_state(const std::string& actor, const std::string& location, int64_t fence);

    void admission(Db& tx, const std::string& location, const std::optional<std::string>& account, const std::string& excluding = "");
    json require_entity(Db& tx, const std::string& actor, const json& entity_id, const json& fence, const json& version = json(), bool alive = false);
    void authorize_entity(Db& tx, const std::string& actor, const json& entity_id, const json& fence);

private:
    std::string checkpoint_state(Db& tx, const std::string& entity_id, const json& state);
    void endpoint(Db& tx, const std::string& actor, const std::string& location, int64_t fence, const json& kind, const json& holder,
                  const json& requester = json());
    void check_capacity(Db& tx, const std::string& kind, const std::string& holder);
    json die_in(Db& tx, const json& row, const std::string& cause, double occurred_ms, const json& evidence);
    json cleanup_in(Db& tx, const json& row, const json& payload, double at);
    std::pair<json, bool> cleanup_batch(Db& tx, const json& event);
    bool quest_required(Db& tx, const std::string& entity_id);
};

class Transfers
{
public:
    Transfers(World& world, Ownership& ownership, const std::string& signing_key);
    json prepare(const std::string& actor, const std::string& command_id, const json& args);
    json claim(const std::string& actor, const std::string& command_id, const json& args);
    json commit(const std::string& actor, const std::string& command_id, const json& args);
    json abort(const std::string& actor, const std::string& command_id, const json& args);
    json status(const std::string& actor, const json& transfer_id);
    json verify(const json& token);

private:
    World& world_;
    Store& store_;
    Ownership& ownership_;
    std::string key_;
    size_t checkpoint_limit_ = 1024 * 1024;
    std::string checkpoint_in(Db& tx, const std::vector<std::string>& ids);
    std::string sign(const json& claims);
    json abort_in(Db& tx, const json& row, const std::string& actor, int64_t source_fence, const json& payload);
    void expire_unclaimed(Db& tx, const std::string& actor, const std::string& location, int64_t fence);
    json public_view(Db& tx, const json& row, bool checkpoint = false);
};

class PlayerSaves
{
public:
    PlayerSaves(World& world, Ownership& ownership);
    json inspect(const std::string& actor, const std::string& account, int64_t slot, const std::string& location, int64_t fence, int64_t epoch);
    json begin(const std::string& actor, const std::string& command_id, const json& args);
    json append(const std::string& actor, const std::string& command_id, const json& args);
    json finish(const std::string& actor, const std::string& command_id, const json& args);
    json cancel(const std::string& actor, const std::string& command_id, const json& args);
    json read(const std::string& actor, const std::string& character_id, int64_t fence, int64_t session_fence, int64_t revision,
              int64_t offset, const std::optional<std::string>& transfer_id);

private:
    World& world_;
    Store& store_;
    Ownership& ownership_;
    json authorize(Db& tx, const std::string& actor, const json& character_id, const json& fence, const json& session_fence);
    json upload(Db& tx, const std::string& actor, const json& character_id, const json& fence, const json& session_fence, const json& upload_id);
    int64_t revision(Db& tx, const std::string& character_id);
};

// native_save.py
struct NativeSave
{
	unsigned lives_remaining = 5;
    int version = 0;
    std::string sha256;
    int64_t bytes = 0, items = 0, safe_items = 0, progress_bytes = 0, actor_bytes = 0, inventory_cells = 0;
    json summary() const;
};
NativeSave parse_native_save(const std::string& data);
std::string native_identity(uint64_t world_id, uint64_t seed, const std::string& account, int64_t slot);
constexpr int64_t NATIVE_FILE_LIMIT = 20 * 1024 * 1024;
} // namespace lzm

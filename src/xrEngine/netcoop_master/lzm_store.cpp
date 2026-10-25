#include "lzm_store.h"

#include <windows.h>

namespace lzm
{
static const char* SCHEMA = R"SQL(
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO metadata VALUES ('schema','6');
CREATE TABLE native_player_import (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 10),
 location TEXT NOT NULL, world_id TEXT NOT NULL, seed TEXT NOT NULL,
 sha256 TEXT NOT NULL, summary TEXT NOT NULL, payload_base64 TEXT NOT NULL,
 UNIQUE(account,slot));
CREATE TABLE native_player_save (
 character_id TEXT NOT NULL REFERENCES character(id), revision INTEGER NOT NULL CHECK(revision>0),
 sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL, summary TEXT NOT NULL, payload_base64 TEXT NOT NULL,
 PRIMARY KEY(character_id,revision));
CREATE TABLE native_player_upload (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL UNIQUE REFERENCES character(id),
 writer TEXT NOT NULL, fence INTEGER NOT NULL, session_fence INTEGER NOT NULL, epoch INTEGER NOT NULL,
 entity_version INTEGER NOT NULL, base_revision INTEGER NOT NULL, slot INTEGER NOT NULL,
 byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL, received INTEGER NOT NULL, expires_ms INTEGER NOT NULL);
CREATE TABLE native_player_part (
 upload_id TEXT NOT NULL REFERENCES native_player_upload(id) ON DELETE CASCADE,
 offset INTEGER NOT NULL, payload_base64 TEXT NOT NULL, PRIMARY KEY(upload_id,offset));
CREATE TABLE world (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), world_id TEXT NOT NULL,
 seed TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>0),
 world_ms REAL NOT NULL CHECK(world_ms>=0), scale REAL NOT NULL CHECK(scale>0 AND scale<=1000),
 sequence INTEGER NOT NULL CHECK(sequence>0), revision INTEGER NOT NULL CHECK(revision>0),
 event_highwater REAL NOT NULL CHECK(event_highwater>=0));
CREATE TABLE location_lease (
 location TEXT PRIMARY KEY, owner TEXT NOT NULL, fence INTEGER NOT NULL CHECK(fence>0),
 expires_ms INTEGER NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>0 AND capacity<=128));
CREATE TABLE world_state (
 name TEXT PRIMARY KEY, version INTEGER NOT NULL CHECK(version>0), state TEXT NOT NULL);
CREATE TABLE entity (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, location TEXT NOT NULL,
 writer TEXT NOT NULL, fence INTEGER NOT NULL CHECK(fence>0),
 version INTEGER NOT NULL CHECK(version>0), alive INTEGER NOT NULL CHECK(alive IN (0,1)),
 state TEXT NOT NULL);
CREATE INDEX entity_location ON entity(location,kind);
CREATE TABLE group_member (
 group_id TEXT NOT NULL REFERENCES entity(id), member_id TEXT PRIMARY KEY REFERENCES entity(id));
CREATE TABLE container (
 id TEXT PRIMARY KEY REFERENCES entity(id), policy TEXT NOT NULL,
 owner TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>=0),
 version INTEGER NOT NULL CHECK(version>0), state TEXT NOT NULL);
CREATE TABLE item (
 id TEXT PRIMARY KEY, section TEXT NOT NULL, kind TEXT NOT NULL,
 holder TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 version INTEGER NOT NULL CHECK(version>0), state TEXT NOT NULL);
CREATE INDEX item_holder ON item(kind,holder,id);
CREATE TABLE character (
 id TEXT PRIMARY KEY REFERENCES entity(id), account TEXT NOT NULL,
 session_fence INTEGER NOT NULL CHECK(session_fence>0), state TEXT NOT NULL);
CREATE INDEX character_account ON character(account);
CREATE TABLE player_session (
 character_id TEXT PRIMARY KEY REFERENCES character(id), account TEXT NOT NULL,
 owner TEXT NOT NULL, fence INTEGER NOT NULL CHECK(fence>0),
 state TEXT NOT NULL CHECK(state IN('ACTIVE','FROZEN','DISCONNECTED')));
CREATE UNIQUE INDEX session_active_account ON player_session(account) WHERE state IN('ACTIVE','FROZEN');
CREATE TABLE transfer (
 id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entity(id),
 source TEXT NOT NULL, target TEXT NOT NULL, source_owner TEXT NOT NULL,
 source_fence INTEGER NOT NULL, target_owner TEXT, target_fence INTEGER,
 state TEXT NOT NULL CHECK(state IN ('PREPARED','CLAIMED','COMMITTED','ABORTED')),
 expires_ms INTEGER NOT NULL, token_hash TEXT NOT NULL, checkpoint TEXT NOT NULL,
 entity_version INTEGER NOT NULL, created_epoch INTEGER NOT NULL);
CREATE INDEX transfer_target ON transfer(target,state);
CREATE UNIQUE INDEX transfer_active ON transfer(entity_id) WHERE state IN ('PREPARED','CLAIMED');
CREATE TABLE quest (
 character_id TEXT NOT NULL REFERENCES character(id), id TEXT NOT NULL,
 stage INTEGER NOT NULL CHECK(stage>=0), version INTEGER NOT NULL CHECK(version>0),
 state TEXT NOT NULL, rewarded INTEGER NOT NULL CHECK(rewarded IN(0,1)),
 PRIMARY KEY(character_id,id));
CREATE TABLE quest_requirement (
 character_id TEXT NOT NULL, quest_id TEXT NOT NULL,
 entity_id TEXT NOT NULL REFERENCES entity(id), alive_required INTEGER NOT NULL,
 policy TEXT NOT NULL, PRIMARY KEY(character_id,quest_id,entity_id),
 FOREIGN KEY(character_id,quest_id) REFERENCES quest(character_id,id));
CREATE INDEX requirement_entity ON quest_requirement(entity_id);
CREATE TABLE quest_event (
 character_id TEXT NOT NULL, quest_id TEXT NOT NULL, event_sequence INTEGER NOT NULL,
 PRIMARY KEY(character_id,quest_id,event_sequence),
 FOREIGN KEY(character_id,quest_id) REFERENCES quest(character_id,id),
 FOREIGN KEY(event_sequence) REFERENCES world_event(sequence));
CREATE TABLE world_event (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 aggregate_id TEXT NOT NULL, aggregate_sequence INTEGER NOT NULL,
 epoch INTEGER NOT NULL, world_ms REAL NOT NULL, type TEXT NOT NULL,
 payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
 UNIQUE(aggregate_id,aggregate_sequence));
CREATE TABLE outbox (
 event_sequence INTEGER PRIMARY KEY REFERENCES world_event(sequence), topic TEXT NOT NULL);
CREATE TABLE outbox_ack (
 consumer TEXT NOT NULL, event_sequence INTEGER NOT NULL REFERENCES outbox(event_sequence),
 PRIMARY KEY(consumer,event_sequence));
CREATE TABLE inbox (
 consumer TEXT NOT NULL, message_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 result TEXT NOT NULL, PRIMARY KEY(consumer,message_id));
CREATE TABLE command_result (
 actor TEXT NOT NULL, id TEXT NOT NULL, payload_hash TEXT NOT NULL, result TEXT NOT NULL,
 PRIMARY KEY(actor,id));
CREATE TABLE scheduled_event (
 id TEXT PRIMARY KEY, due_world_ms REAL NOT NULL, priority INTEGER NOT NULL,
 aggregate_id TEXT NOT NULL, expected_version INTEGER NOT NULL,
 type TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN('PENDING','APPLIED','CANCELLED')),
 payload TEXT NOT NULL, result TEXT);
CREATE INDEX scheduled_due ON scheduled_event(state,due_world_ms,priority,id);
CREATE TABLE route (
 entity_id TEXT PRIMARY KEY REFERENCES entity(id), version INTEGER NOT NULL CHECK(version>0),
 location TEXT NOT NULL, points TEXT NOT NULL, started_ms REAL NOT NULL,
 arrival_ms REAL NOT NULL, speed_real REAL NOT NULL CHECK(speed_real>0),
 active INTEGER NOT NULL CHECK(active IN(0,1)), seed TEXT NOT NULL);
CREATE TABLE snapshot (
 id TEXT PRIMARY KEY, schema INTEGER NOT NULL, epoch INTEGER NOT NULL,
 watermark INTEGER NOT NULL, checksum TEXT NOT NULL, payload TEXT NOT NULL);
)SQL";

static const char* MIGRATIONS[] = {
    // 1 -> 2
    R"SQL(
CREATE TABLE world_state(name TEXT PRIMARY KEY,version INTEGER NOT NULL CHECK(version>0),state TEXT NOT NULL);
CREATE TABLE group_member(group_id TEXT NOT NULL REFERENCES entity(id),member_id TEXT PRIMARY KEY REFERENCES entity(id));
INSERT INTO group_member SELECT e.id,j.value FROM entity e,json_each(e.state,'$.member_ids') j WHERE e.kind='GROUP';
CREATE TABLE quest_event(character_id TEXT NOT NULL,quest_id TEXT NOT NULL,event_sequence INTEGER NOT NULL,
 PRIMARY KEY(character_id,quest_id,event_sequence),
 FOREIGN KEY(character_id,quest_id) REFERENCES quest(character_id,id),
 FOREIGN KEY(event_sequence) REFERENCES world_event(sequence));
UPDATE metadata SET value='2' WHERE key='schema';
)SQL",
    // 2 -> 3
    R"SQL(
CREATE TABLE route(entity_id TEXT PRIMARY KEY REFERENCES entity(id),version INTEGER NOT NULL CHECK(version>0),
 location TEXT NOT NULL,points TEXT NOT NULL,started_ms REAL NOT NULL,arrival_ms REAL NOT NULL,
 speed_real REAL NOT NULL CHECK(speed_real>0),active INTEGER NOT NULL CHECK(active IN(0,1)),seed TEXT NOT NULL);
UPDATE metadata SET value='3' WHERE key='schema';
)SQL",
    // 3 -> 4
    R"SQL(
DROP INDEX item_holder;
CREATE INDEX item_holder ON item(kind,holder,id);
UPDATE metadata SET value='4' WHERE key='schema';
)SQL",
    // 4 -> 5
    R"SQL(
CREATE TABLE native_player_import (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 10),
 location TEXT NOT NULL, world_id TEXT NOT NULL, seed TEXT NOT NULL,
 sha256 TEXT NOT NULL, summary TEXT NOT NULL, payload_base64 TEXT NOT NULL,
 UNIQUE(account,slot));
UPDATE metadata SET value='5' WHERE key='schema';
)SQL",
    // 5 -> 6
    R"SQL(
CREATE TABLE native_player_save (
 character_id TEXT NOT NULL REFERENCES character(id), revision INTEGER NOT NULL CHECK(revision>0),
 sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL, summary TEXT NOT NULL, payload_base64 TEXT NOT NULL,
 PRIMARY KEY(character_id,revision));
CREATE TABLE native_player_upload (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL UNIQUE REFERENCES character(id),
 writer TEXT NOT NULL, fence INTEGER NOT NULL, session_fence INTEGER NOT NULL, epoch INTEGER NOT NULL,
 entity_version INTEGER NOT NULL, base_revision INTEGER NOT NULL, slot INTEGER NOT NULL,
 byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL, received INTEGER NOT NULL, expires_ms INTEGER NOT NULL);
CREATE TABLE native_player_part (
 upload_id TEXT NOT NULL REFERENCES native_player_upload(id) ON DELETE CASCADE,
 offset INTEGER NOT NULL, payload_base64 TEXT NOT NULL, PRIMARY KEY(upload_id,offset));
UPDATE metadata SET value='6' WHERE key='schema';
)SQL",
};

Store::Store(const std::wstring& file) : path(file)
{
    DWORD attributes = GetFileAttributesW(path.c_str());
    bool existed = attributes != INVALID_FILE_ATTRIBUTES;
    if (existed)
    {
        WIN32_FILE_ATTRIBUTE_DATA data{};
        GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data);
        if (data.nFileSizeHigh == 0 && data.nFileSizeLow == 0)
            throw Unavailable("existing database is empty; explicit recovery is required");
    }
    // The same one-byte lock Python's msvcrt.locking takes: one service per DB.
    HANDLE handle = CreateFileW((path + L".service.lock").c_str(), GENERIC_READ | GENERIC_WRITE,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (handle == INVALID_HANDLE_VALUE) throw Unavailable("world database lock cannot be opened");
    LARGE_INTEGER size{};
    GetFileSizeEx(handle, &size);
    if (size.QuadPart == 0)
    {
        DWORD written = 0;
        char zero = 0;
        WriteFile(handle, &zero, 1, &written, nullptr);
        FlushFileBuffers(handle);
    }
    OVERLAPPED at{};
    if (!LockFileEx(handle, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &at))
    {
        CloseHandle(handle);
        throw Unavailable("another master already owns this world database");
    }
    lock_file_ = handle;
    try
    {
        db.open(path);
        db.exec("PRAGMA foreign_keys=ON");
        db.one("PRAGMA journal_mode=WAL");
        db.exec("PRAGMA synchronous=FULL");
        if (db.scalar("PRAGMA quick_check") != "ok") throw Unavailable("database integrity check failed");
        auto tables = db.all("SELECT name FROM sqlite_master WHERE type='table'");
        if (tables.empty())
        {
            if (existed) throw Unavailable("existing database has no schema; refusing to create another world");
            db.script(std::string("BEGIN IMMEDIATE;\n") + SCHEMA + "\nCOMMIT;");
        }
        json version = db.scalar("SELECT value FROM metadata WHERE key='schema'");
        for (int from = 1; from <= 5; ++from)
        {
            if (version.is_string() && version.get<std::string>() == std::to_string(from))
            {
                db.script(std::string("BEGIN IMMEDIATE;\n") + MIGRATIONS[from - 1] + "\nCOMMIT;");
                version = db.scalar("SELECT value FROM metadata WHERE key='schema'");
            }
        }
        if (!version.is_string() || version.get<std::string>() != "6") throw Unavailable("unsupported database schema");
        if (!db.one("PRAGMA foreign_key_check").is_null()) throw Unavailable("database ownership references are inconsistent");
        db.exec("CREATE INDEX IF NOT EXISTS entity_writer_cursor ON entity(location,writer,fence,id)");
        db.exec("CREATE INDEX IF NOT EXISTS item_inventory_cursor ON item(holder,id) WHERE kind NOT IN ('WORLD','DESTROYED')");
        // Accounts (owner 2026-10-25, doc 154): the master is their only store,
        // the locations keep a mirror. Beside the world schema, not in its
        // version: the Python service ignores the table.
        db.exec("CREATE TABLE IF NOT EXISTS account(key TEXT PRIMARY KEY, login TEXT NOT NULL, role TEXT NOT NULL,"
                " salt TEXT NOT NULL, hash TEXT NOT NULL, money INTEGER, device TEXT NOT NULL, approval TEXT NOT NULL,"
                " firebase_uid TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0))");
        db.exec("CREATE INDEX IF NOT EXISTS account_revision ON account(revision)");
    }
    catch (...)
    {
        close();
        throw;
    }
}

Store::~Store() { close(); }

void Store::close()
{
    std::lock_guard<std::recursive_mutex> guard(lock);
    db.close();
    if (lock_file_)
    {
        CloseHandle((HANDLE)lock_file_);
        lock_file_ = nullptr;
    }
}

void Store::require_epoch(Db& tx)
{
    json row = tx.one("SELECT epoch FROM world WHERE singleton=1");
    if (row.is_null() || !epoch || row["epoch"].get<int64_t>() != *epoch)
        throw Unavailable("world authority is not ready");
}

json Store::command(const std::string& actor, const std::string& command_id, const json& payload, const Apply& apply,
                    const Check& authorize, const Replay& validate_replay)
{
    identifier(actor);
    persistent_id(command_id);
    std::string digest = sha256_hex(canonical(payload));
    return transaction([&](Db& tx) -> json {
        require_epoch(tx);
        if (authorize) authorize(tx);
        json old = tx.one("SELECT * FROM command_result WHERE actor=? AND id=?", { actor, command_id });
        if (!old.is_null())
        {
            if (old["payload_hash"] != digest) throw Conflict("idempotency key reused for another command");
            json result = loads(old["result"].get<std::string>());
            if (validate_replay) validate_replay(tx, result);
            return result;
        }
        json result = apply(tx);
        tx.exec("INSERT INTO command_result VALUES(?,?,?,?)", { actor, command_id, digest, canonical(result) });
        return result;
    });
}

int64_t Store::event(Db& tx, const std::string& aggregate, const std::string& type, const json& payload, double world_ms,
                     const std::string& topic, std::optional<double> committed)
{
    require_epoch(tx);
    identifier(aggregate);
    identifier(type);
    identifier(topic);
    finite(world_ms);
    double committed_ms = committed ? finite(*committed) : world_ms;
    if (committed_ms < world_ms) throw Invalid("event cannot be committed before it occurred");
    std::string encoded = canonical(payload);
    double highwater = tx.scalar("SELECT event_highwater FROM world WHERE singleton=1").get<double>();
    int64_t seq = tx.scalar("SELECT COALESCE(MAX(aggregate_sequence),0)+1 FROM world_event WHERE aggregate_id=?", { aggregate }).get<int64_t>();
    tx.exec("INSERT INTO world_event(id,aggregate_id,aggregate_sequence,epoch,world_ms,type,payload,payload_hash) VALUES(?,?,?,?,?,?,?,?)",
            { uuid4_hex(), aggregate, seq, *epoch, world_ms, type, encoded, sha256_hex(encoded) });
    int64_t sequence = tx.last_rowid();
    tx.exec("INSERT INTO outbox VALUES(?,?)", { sequence, topic });
    tx.exec("UPDATE world SET event_highwater=?, revision=revision+1 WHERE singleton=1", { std::max(highwater, committed_ms) });
    return sequence;
}

int64_t Store::journal_floor(Db& tx)
{
    json row = tx.one("SELECT value FROM metadata WHERE key='journal_floor'");
    return row.is_null() ? 0 : parse_int(row["value"].get<std::string>());
}

std::vector<json> Store::events(int64_t after, int64_t limit)
{
    if (after < 0 || limit < 1 || limit > 512) throw Invalid("invalid event page");
    std::lock_guard<std::recursive_mutex> guard(lock);
    require_epoch(db);
    if (after < journal_floor(db))
        throw Unavailable("journal history before the compaction floor is gone; start from a snapshot");
    auto rows = db.all("SELECT * FROM world_event WHERE sequence>? ORDER BY sequence LIMIT ?", { after, limit });
    for (auto& row : rows) row["payload"] = loads(row["payload"].get<std::string>());
    return rows;
}

json Store::snapshot(size_t byte_limit)
{
    if (byte_limit < 1024 || byte_limit > size_t(128) * 1024 * 1024) throw Invalid("invalid backend snapshot byte budget");
    return transaction([&](Db& tx) -> json {
        require_epoch(tx);
        static const char* names[] = { "world", "world_state", "location_lease", "entity", "group_member", "container", "item",
                                       "character", "player_session", "transfer", "quest", "quest_requirement", "quest_event",
                                       "scheduled_event", "route", "native_player_import", "native_player_save" };
        int64_t watermark = tx.scalar("SELECT COALESCE(MAX(sequence),0) FROM world_event").get<int64_t>();
        json records = json::object();
        for (const char* name : names) records[name] = json::array();
        json payload = { { "schema", 1 }, { "epoch", *epoch }, { "watermark", watermark }, { "records", records } };
        size_t used = canonical(payload, byte_limit).size();
        for (const char* name : names)
        {
            for (auto& row : tx.all(std::string("SELECT * FROM ") + name + " ORDER BY rowid"))
            {
                used += canonical(row, byte_limit).size() + (payload["records"][name].empty() ? 0 : 1);
                if (used > byte_limit) throw Invalid("backend snapshot exceeds admission byte budget");
                payload["records"][name].push_back(row);
            }
        }
        std::string encoded = canonical(payload, byte_limit);
        std::string checksum = sha256_hex(encoded);
        std::string id = uuid4_hex();
        tx.exec("INSERT INTO snapshot VALUES(?,?,?,?,?,?)", { id, 1, *epoch, watermark, checksum, encoded });
        return json{ { "id", id }, { "watermark", watermark }, { "checksum", checksum } };
    });
}
} // namespace lzm

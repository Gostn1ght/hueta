#pragma once
#include <algorithm>
#include <cstring>
#include <utility>
#include <vector>

// Stable network identity of stalker cycle animations (doc 204).
//
// A MotionID is a local (OMF slot, index) pair. Two processes can load the same
// visual with a different slot order (modded libraries are appended, wildcard
// OMF lists follow the file system), so a raw MotionID from the server can name
// a different animation, or none, on a client. The wire therefore carries a
// 32-bit FNV-1a hash of the cycle name; each side maps it through an immutable
// table built from its own skeleton.
//
// Rules:
// * a name resolves like CKinematicsAnimated::ID_Cycle_Safe: the highest slot
//   that contains it wins. The same name in several slots is an alias;
// * distinct names with one hash are ambiguous, permanently, however many
//   names share it; such hashes are neither encoded nor decoded;
// * a local ID with several names encodes deterministically: names that
//   resolve to this ID first, then the smallest name (strcmp);
// * the hash equal to motion_wire_invalid is never used.
// The table stores no names or visual pointers, so it cannot dangle.
namespace netcoop
{
static const u32 motion_wire_invalid = u32(-1);
// High bit of the snapshot animation mode: the three values are name hashes.
// Without it they are legacy raw MotionID values.
static const u8 motion_mode_hashed = 0x80;
static const u8 motion_mode_mask = 0x7f;

inline u32 motion_name_hash(const char* name)
{
    u32 hash = 2166136261u;
    for (const unsigned char* c = reinterpret_cast<const unsigned char*>(name); *c; ++c)
        hash = (hash ^ *c) * 16777619u;
    return hash;
}

inline u32 motion_key(u16 slot, u16 idx) { return (u32(slot) << 16) | u32(idx); }

struct MotionIdentityEntry
{
    const char* name; // only needs to live during build()
    u16 slot;
    u16 idx;
};

class MotionIdentityTable
{
    typedef std::pair<u32, u32> Pair;
    std::vector<Pair> encode_; // local key -> hash, sorted by key
    std::vector<Pair> decode_; // hash -> canonical local key, sorted by hash
    std::vector<u32> local_; // every local cycle key, sorted
    bool built_ = false;

    static bool find(const std::vector<Pair>& table, u32 key, u32& value)
    {
        auto it = std::lower_bound(table.begin(), table.end(), Pair(key, 0u),
            [](const Pair& a, const Pair& b) { return a.first < b.first; });
        if (it == table.end() || it->first != key)
            return false;
        value = it->second;
        return true;
    }

public:
    bool built() const { return built_; }
    void reset()
    {
        encode_.clear();
        decode_.clear();
        local_.clear();
        built_ = false;
    }

    template <class Hash>
    void build(std::vector<MotionIdentityEntry> entries, Hash hash)
    {
        reset();
        auto by_name = [](const MotionIdentityEntry& a, const MotionIdentityEntry& b)
        {
            const int order = std::strcmp(a.name, b.name);
            if (order)
                return order < 0;
            if (a.slot != b.slot)
                return a.slot > b.slot; // ID_Cycle_Safe: highest slot first
            return a.idx < b.idx;
        };
        entries.erase(std::remove_if(entries.begin(), entries.end(),
            [](const MotionIdentityEntry& e) { return !e.name || !*e.name; }), entries.end());
        std::sort(entries.begin(), entries.end(), by_name);
        for (const MotionIdentityEntry& e : entries)
            local_.push_back(motion_key(e.slot, e.idx));
        std::sort(local_.begin(), local_.end());
        local_.erase(std::unique(local_.begin(), local_.end()), local_.end());

        struct Name { const char* name; u32 hash; u32 canonical; bool ambiguous; };
        std::vector<Name> names;
        for (const MotionIdentityEntry& e : entries)
            if (names.empty() || std::strcmp(names.back().name, e.name))
                names.push_back({e.name, hash(e.name), motion_key(e.slot, e.idx), false});

        std::vector<size_t> order(names.size());
        for (size_t i = 0; i < order.size(); ++i)
            order[i] = i;
        std::sort(order.begin(), order.end(), [&](size_t a, size_t b) { return names[a].hash < names[b].hash; });
        for (size_t i = 0; i < order.size();)
        {
            size_t j = i + 1;
            while (j < order.size() && names[order[j]].hash == names[order[i]].hash)
                ++j;
            // names are unique here, so a group of two or more is a collision
            const bool ambiguous = j - i > 1 || names[order[i]].hash == motion_wire_invalid;
            for (size_t k = i; k < j; ++k)
            {
                names[order[k]].ambiguous = ambiguous;
                if (!ambiguous)
                    decode_.push_back(Pair(names[order[k]].hash, names[order[k]].canonical));
            }
            i = j;
        }

        struct Candidate { u32 key; bool canonical; const char* name; u32 hash; };
        std::vector<Candidate> candidates;
        size_t n = 0;
        for (const MotionIdentityEntry& e : entries)
        {
            while (std::strcmp(names[n].name, e.name))
                ++n;
            if (names[n].ambiguous)
                continue;
            const u32 key = motion_key(e.slot, e.idx);
            candidates.push_back({key, key == names[n].canonical, e.name, names[n].hash});
        }
        std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b)
        {
            if (a.key != b.key)
                return a.key < b.key;
            if (a.canonical != b.canonical)
                return a.canonical;
            return std::strcmp(a.name, b.name) < 0;
        });
        for (const Candidate& c : candidates)
            if (encode_.empty() || encode_.back().first != c.key)
                encode_.push_back(Pair(c.key, c.hash));
        built_ = true;
    }

    void build(std::vector<MotionIdentityEntry> entries) { build(std::move(entries), motion_name_hash); }

    // Wire value for a local cycle, or motion_wire_invalid.
    u32 encode(u16 slot, u16 idx) const
    {
        u32 hash = motion_wire_invalid;
        return find(encode_, motion_key(slot, idx), hash) ? hash : motion_wire_invalid;
    }

    // Local key for a wire hash; false when unknown, ambiguous or invalid.
    bool decode(u32 hash, u32& key) const
    {
        return hash != motion_wire_invalid && find(decode_, hash, key);
    }

    // A legacy raw MotionID is accepted only if it names an existing local
    // cycle; it can still be the wrong animation when OMF orders differ.
    bool legacy(u32 raw_key) const
    {
        return std::binary_search(local_.begin(), local_.end(), raw_key);
    }

    size_t size() const { return decode_.size(); }
};

// Decodes one snapshot. base_mode gets the mode without the protocol bit.
// Returns false (use the local animation selection) unless every animation the
// mode needs resolves; the optional head of mode 3 becomes motion_wire_invalid.
inline bool resolve_motion_snapshot(const MotionIdentityTable& table, u8 mode, const u32 (&wire)[3],
    u32 (&keys)[3], u8& base_mode)
{
    base_mode = u8(mode & motion_mode_mask);
    const bool hashed = (mode & motion_mode_hashed) != 0;
    for (int i = 0; i < 3; ++i)
    {
        keys[i] = motion_wire_invalid;
        if (wire[i] == motion_wire_invalid)
            continue;
        if (hashed ? !table.decode(wire[i], keys[i]) : !table.legacy(wire[i]))
            keys[i] = motion_wire_invalid;
        else if (!hashed)
            keys[i] = wire[i];
    }
    switch (base_mode)
    {
    case 1:
    case 2: return keys[0] != motion_wire_invalid;
    case 3: return keys[1] != motion_wire_invalid && keys[2] != motion_wire_invalid;
    default: return false;
    }
}
} // namespace netcoop
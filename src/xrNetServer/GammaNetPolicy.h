#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>

// 128 human players; the headless ALife host needs one internal client state.
namespace gamma_net
{
constexpr unsigned max_players = 128;
constexpr unsigned max_client_states = max_players + 1;
constexpr unsigned protocol_version = 2; // Corrected compressed-packet CRC range.

inline bool newer(std::uint32_t a, std::uint32_t b)
{
    const auto delta = a - b;
    return delta != 0 && delta < 0x80000000u;
}

// CActor::net_Export: 59 movement bytes, three equipment ids, a NUL-terminated
// visual, optional owner platform/sample sequence, a two-byte body count,
// and optionally one 77-byte physics state. Keep legacy clients readable.
// Validate before the host imports floats into movement/physics state.
inline bool valid_coop_actor(const unsigned char* data, std::size_t size)
{
    if (!data || size < 68) return false;
    const auto* end = static_cast<const unsigned char*>(std::memchr(data + 65, 0, size - 65));
    if (!end || end - (data + 65) > 1023) return false;
    std::size_t count_offset = std::size_t(end - data) + 1;
    if (size - count_offset >= 2 && data[count_offset] == 0x4c && data[count_offset + 1] == 0x50)
    {
        if (size - count_offset < 18) return false;
        for (std::size_t offset = count_offset + 4; offset < count_offset + 16; offset += 4)
        {
            float value; std::memcpy(&value, data + offset, sizeof(value));
            if (!std::isfinite(value) || std::fabs(value) > 100000.0f) return false;
        }
        count_offset += 16;
        if (size - count_offset >= 2 && data[count_offset] == 0x4e && data[count_offset + 1] == 0x53)
        {
            if (size - count_offset < 8) return false;
            count_offset += 6;
        }
    }
    if (count_offset + 2 > size || data[count_offset + 1] != 0 || data[count_offset] > 1) return false;
    const std::size_t body_offset = count_offset + 2;
    if (size != body_offset + (data[count_offset] ? 77u : 0u)) return false;
    const unsigned offsets[] = {0, 9, 13, 17, 21, 25, 29, 33, 44, 50, 54};
    for (auto offset : offsets)
    {
        float value;
        std::memcpy(&value, data + offset, sizeof(value));
        if (!std::isfinite(value) || std::fabs(value) > 100000.0f) return false;
    }
    if (data[count_offset])
    {
        if (data[body_offset] > 1) return false;
        for (std::size_t offset = body_offset + 1; offset < size; offset += 4)
        {
            float value;
            std::memcpy(&value, data + offset, sizeof(value));
            if (!std::isfinite(value) || std::fabs(value) > 1000000.0f) return false;
        }
    }
    return true;
}

// Parse one complete slash-delimited option, without atoi overflow or substring matches.
inline unsigned player_limit(const char* options)
{
    for (const char* p = options; p && *p;)
    {
        if (std::strncmp(p, "maxplayers=", 11) == 0)
        {
            p += 11;
            unsigned value = 0;
            bool digit = false;
            for (; *p && *p != '/'; ++p)
            {
                if (*p < '0' || *p > '9' || value > max_players)
                    return max_players;
                digit = true;
                value = value * 10 + unsigned(*p - '0');
            }
            return digit && value >= 1 && value <= max_players ? value : max_players;
        }
        p = std::strchr(p, '/');
        if (p) ++p;
    }
    return max_players;
}

// Validate the entire merged frame before delivering any contained message.
inline bool valid_frame(const unsigned char* data, std::size_t size, bool merged,
                        std::size_t packet_limit)
{
    if (!data || size < 2) return false;
    if (!merged) return size < packet_limit;
    std::size_t pos = 0;
    while (pos < size)
    {
        if (size - pos < 2) return false;
        const std::size_t n = data[pos] | (std::size_t(data[pos + 1]) << 8);
        pos += 2;
        if (n < 2 || n >= packet_limit || n > size - pos) return false;
        pos += n;
    }
    return true;
}
}

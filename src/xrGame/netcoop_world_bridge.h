#pragma once

// Read-only transport. This does not adopt a remote clock or ownership. Keep
// this header private to the adapter .cpp, never in shared engine headers.
#include "netcoop_world_clock.h"
#include "../3rd party/nlohmann/json.hpp"
#include <string>
#include <utility>
#include <type_traits>
#ifdef _WIN32
#include <windows.h>
#include <winhttp.h>
#pragma comment(lib,"winhttp.lib")
#endif

namespace netcoop_world
{
using BridgeJson = nlohmann::json;
inline BridgeJson bridge_json(const std::string& encoded, std::size_t limit)
{
    if (encoded.empty() || encoded.size()>limit) throw std::invalid_argument("bridge JSON budget");
    unsigned depth=0;
    bool string=false,escape=false;
    for (const char c : encoded)
    {
        if (string)
        {
            if (escape) escape=false;
            else if (c=='\\') escape=true;
            else if (c=='"') string=false;
        }
        else if (c=='"') string=true;
        else if (c=='{' || c=='[')
        { if (++depth>64) throw std::invalid_argument("bridge JSON nesting budget"); }
        else if (c=='}' || c==']')
        { if (!depth) throw std::invalid_argument("bridge JSON brackets");--depth; }
    }
    if (depth || string) throw std::invalid_argument("incomplete bridge JSON");
    return BridgeJson::parse(encoded,nullptr,false);
}
inline std::uint64_t bridge_unsigned(const BridgeJson& object, const char* key)
{
    if (!object.is_object()) throw std::invalid_argument("invalid bridge object");
    const auto found=object.find(key);
    if (found==object.end() || !found->is_number_integer()) throw std::invalid_argument("invalid bridge integer");
    if (found->is_number_unsigned()) return found->get<std::uint64_t>();
    const auto value=found->get<std::int64_t>();
    if (value<0) throw std::invalid_argument("negative bridge integer");
    return std::uint64_t(value);
}
inline double bridge_number(const BridgeJson& object, const char* key)
{
    if (!object.is_object()) throw std::invalid_argument("invalid bridge object");
    const auto found=object.find(key);
    if (found==object.end() || !found->is_number()) throw std::invalid_argument("invalid bridge number");
    return found->get<double>();
}
inline WorldStateSnapshot parse_bridge_world(const BridgeJson& state)
{
    if (bridge_unsigned(state,"schema")!=1 || !state.contains("clock") || !state["clock"].is_object() ||
        !state.contains("states") || !state["states"].is_object()) throw std::invalid_argument("invalid world bootstrap");
    const auto& clock=state["clock"];
    if (bridge_unsigned(clock,"schema")!=clock_schema) throw std::invalid_argument("unsupported clock schema");
    WorldStateSnapshot result;
    result.world_seed=bridge_unsigned(state,"world_seed");
    result.state_revision=bridge_unsigned(state,"state_revision");
    result.clock={clock_schema,bridge_unsigned(clock,"world_id"),bridge_unsigned(clock,"authority_epoch"),
        bridge_unsigned(clock,"sequence"),bridge_number(clock,"world_ms"),bridge_number(clock,"time_scale")};
    if (!valid(result.clock) || !result.state_revision || bridge_unsigned(clock,"seed")!=result.world_seed ||
        bridge_unsigned(clock,"revision")!=result.state_revision)
        throw std::invalid_argument("inconsistent clock/world bootstrap");
    return result;
}
inline WorldStateSnapshot parse_bridge_bootstrap(const std::string& encoded)
{
    const auto body=bridge_json(encoded,65536);
    if (!body.is_object() || !body.contains("result") || !body["result"].is_object())
        throw std::invalid_argument("invalid bridge response");
    return parse_bridge_world(body["result"]);
}

// Versioned global schedules travel with the same bootstrap/clock, never as
// independently sampled RPCs. This is still a read-only admission contract.
struct BridgeTimeline
{
    bool present=false;
    std::uint64_t version=0,seed=0;
    std::string id,source,target;
    double warning=0,active=0,peak=0,ended=0,intensity=0;
};
struct BridgeBootstrap
{
    WorldStateSnapshot world{};
    std::uint64_t event_watermark=0;
    BridgeTimeline weather,emission,psi_storm;
};
static_assert(std::is_nothrow_move_assignable<BridgeBootstrap>::value,"bridge mailbox moves must not throw");
inline std::string bridge_identifier(const BridgeJson& object, const char* key, bool persistent=false)
{
    const auto found=object.find(key);
    if (found==object.end() || !found->is_string()) throw std::invalid_argument("invalid timeline identifier");
    auto value=found->get<std::string>();
    const char* allowed=persistent ? "0123456789abcdef" :
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-";
    if (value.empty() || value.size()>(persistent ? 32u:128u) ||
        (persistent && value.size()!=32) || value.find_first_not_of(allowed)!=std::string::npos)
        throw std::invalid_argument("invalid timeline identifier");
    return value;
}
inline double bridge_time(const BridgeJson& object, const char* key)
{
    const auto value=bridge_number(object,key);
    if (!std::isfinite(value) || value<0 || value>max_world_ms)
        throw std::invalid_argument("invalid timeline time");
    return value;
}
inline BridgeTimeline parse_bridge_timeline(const BridgeJson& states, const char* name, bool weather)
{
    const auto found=states.find(name);
    if (found==states.end()) return {};
    const auto& envelope=*found;
    BridgeTimeline result;
    result.version=bridge_unsigned(envelope,"version");
    if (!result.version || result.version>=(std::uint64_t(1)<<63) || !envelope.contains("state") ||
        !envelope["state"].is_object()) throw std::invalid_argument("invalid timeline envelope");
    const auto& state=envelope["state"];
    result.id=bridge_identifier(state,"timeline_id",true);
    if (!state.contains("times") || !state["times"].is_object() ||
        !state.contains("parameters") || !state["parameters"].is_object() ||
        !state.contains("phase") || !state["phase"].is_string())
        throw std::invalid_argument("incomplete global timeline");
    const auto& times=state["times"];
    const auto& parameters=state["parameters"];
    const auto phase=state["phase"].get<std::string>();
    result.seed=bridge_unsigned(parameters,"seed");
    if (weather)
    {
        if (times.size()!=2 || (phase!="SCHEDULED" && phase!="TRANSITION" && phase!="SETTLED"))
            throw std::invalid_argument("invalid weather phases");
        result.active=bridge_time(times,"TRANSITION");
        result.ended=bridge_time(times,"SETTLED");
        result.source=bridge_identifier(parameters,"source");
        result.target=bridge_identifier(parameters,"target");
        if (result.ended<=result.active) throw std::invalid_argument("invalid weather order");
    }
    else
    {
        if (times.size()!=4 || (phase!="SCHEDULED" && phase!="WARNING" && phase!="ACTIVE" &&
            phase!="PEAK" && phase!="ENDED")) throw std::invalid_argument("invalid emission phases");
        result.warning=bridge_time(times,"WARNING");
        result.active=bridge_time(times,"ACTIVE");
        result.peak=bridge_time(times,"PEAK");
        result.ended=bridge_time(times,"ENDED");
        result.intensity=bridge_number(parameters,"intensity");
        if (!(result.warning<result.active && result.active<result.peak && result.peak<result.ended) ||
            !std::isfinite(result.intensity) || result.intensity<=0 || result.intensity>100)
            throw std::invalid_argument("invalid emission order/intensity");
    }
    result.present=true;
    return result;
}
inline BridgeBootstrap parse_bridge_globals(const std::string& encoded)
{
    BridgeBootstrap result;
    const auto body=bridge_json(encoded,65536);
    if (!body.is_object() || !body.contains("result") || !body["result"].is_object())
        throw std::invalid_argument("invalid bridge response");
    const auto& state=body["result"];
    result.world=parse_bridge_world(state);
    result.event_watermark=bridge_unsigned(state,"event_watermark");
    if (result.event_watermark>=(std::uint64_t(1)<<63)) throw std::invalid_argument("invalid event watermark");
    result.weather=parse_bridge_timeline(state["states"],"weather",true);
    result.emission=parse_bridge_timeline(state["states"],"emission",false);
    // Psi storms use the emission's phases (an older master has none).
    result.psi_storm=parse_bridge_timeline(state["states"],"psi_storm",false);
    return result;
}
inline unsigned bridge_weather_phase(const BridgeTimeline& state, double world_ms)
{
    return !state.present ? 0u : world_ms<state.active ? 1u : world_ms<state.ended ? 2u : 3u;
}
inline double bridge_weather_blend(const BridgeTimeline& state, double world_ms)
{
    return !state.present ? 0 : (std::max)(0.0,(std::min)(1.0,(world_ms-state.active)/(state.ended-state.active)));
}
inline unsigned bridge_emission_phase(const BridgeTimeline& state, double world_ms)
{
    return !state.present ? 0u : world_ms<state.warning ? 1u : world_ms<state.active ? 2u :
        world_ms<state.peak ? 3u : world_ms<state.ended ? 4u : 5u;
}
inline bool bridge_timeline_forward(const BridgeTimeline& old, const BridgeTimeline& next)
{
    if (!old.present) return true;
    if (!next.present || next.version<old.version) return false;
    // Same durable version must keep the immutable schedule. Persisted phase
    // can lag analytic playback during recovery and is not a second clock.
    if (next.id!=old.id) return next.version>old.version;
    return next.seed==old.seed &&
        next.source==old.source && next.target==old.target && next.warning==old.warning &&
        next.active==old.active && next.peak==old.peak && next.ended==old.ended && next.intensity==old.intensity;
}

struct BridgeConfig
{
    unsigned port=0;
    std::string token;
    bool bound=false;
    // schema 3 (owner 2026-10-12): the master is the authority for every map
    // of the server folder; one file, bound to the level actually loaded.
    bool authority=false;
    std::uint64_t master_world=0,master_seed=0,local_world=0,local_seed=0;
    std::string location;
    bool matches_local(const WorldStateSnapshot& state, const char* map=nullptr) const
    {
        if (authority) return map && *map;
        return !bound || (state.clock.world_id==local_world && state.world_seed==local_seed &&
                         map && location==map);
    }
    static BridgeConfig parse(const std::string& encoded)
    {
        const auto body=bridge_json(encoded,4096);
        if (!body.is_object()) throw std::invalid_argument("invalid bridge config object");
        const auto schema=bridge_unsigned(body,"schema");
        if ((schema!=1 && schema!=2 && schema!=3) || body.size()!=(schema==1 ? 5u:schema==2 ? 10u:7u) ||
            !body.contains("mode") || body["mode"]!=(schema==3 ? "authority":"shadow") ||
            !body.contains("host") || body["host"]!="127.0.0.1" ||
            !body.contains("token") || !body["token"].is_string()) throw std::invalid_argument("invalid read-only bridge config");
        const auto port=bridge_unsigned(body,"port");
        const auto token=body["token"].get<std::string>();
        if (!port || port>65535 || token.size()<32 || token.size()>256 ||
            token.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
            throw std::invalid_argument("invalid bridge credential/port");
        BridgeConfig result;
        result.port=unsigned(port);result.token=token;
        if (schema==2)
        {
            result.master_world=bridge_unsigned(body,"master_world_id");
            result.master_seed=bridge_unsigned(body,"master_world_seed");
            result.local_world=bridge_unsigned(body,"local_world_id");
            result.local_seed=bridge_unsigned(body,"local_world_seed");
            result.location=bridge_identifier(body,"location");
            if (!result.master_world || !result.local_world) throw std::invalid_argument("zero bridge WorldID");
            result.bound=true;
        }
        if (schema==3)
        {
            result.master_world=bridge_unsigned(body,"master_world_id");
            result.master_seed=bridge_unsigned(body,"master_world_seed");
            if (!result.master_world) throw std::invalid_argument("zero bridge WorldID");
            result.bound=result.authority=true;
        }
        return result;
    }
};

class BridgeObserver
{
    std::uint64_t world_,seed_;
    LocationClock follower_;
    bool bootstrapped_=false;
    BridgeBootstrap globals_{};
    bool have_globals_=false;
public:
    BridgeObserver(std::uint64_t world, std::uint64_t seed) : world_(world),seed_(seed),follower_(world) {}
    SyncResult receive(const WorldStateSnapshot& state, std::uint64_t sent, std::uint64_t received)
    {
        if (state.schema!=1 || !state.state_revision || state.clock.world_id!=world_ || state.world_seed!=seed_)
            return SyncResult::invalid;
        if (!bootstrapped_)
        {
            const auto result=follower_.bootstrap(state.clock,sent,received);
            bootstrapped_=result==SyncResult::applied;
            return result;
        }
        const auto result=follower_.observe(state.clock,sent,received);
        // Full bootstrap was fetched, so a shadow follower may immediately
        // reset its estimate after fencing. Production authority adoption must
        // still pause mutations/catch up and is deliberately not done here.
        if (result==SyncResult::epoch_changed || result==SyncResult::resync_required)
            return follower_.bootstrap(state.clock,sent,received);
        return result;
    }
    bool ready(std::uint64_t now) const { return follower_.ready(now); }
    double estimate(std::uint64_t now) { return follower_.estimate(now); }
    SyncResult receive(const BridgeBootstrap& state, std::uint64_t sent, std::uint64_t received)
    {
        if (have_globals_ && (state.world.state_revision<globals_.world.state_revision ||
            state.event_watermark<globals_.event_watermark ||
            !bridge_timeline_forward(globals_.weather,state.weather) ||
            !bridge_timeline_forward(globals_.emission,state.emission) ||
            !bridge_timeline_forward(globals_.psi_storm,state.psi_storm))) return SyncResult::invalid;
        auto candidate=state; // Allocate before advancing the follower.
        const auto result=receive(state.world,sent,received);
        if (result==SyncResult::applied) {globals_=std::move(candidate);have_globals_=true;}
        return result;
    }
    const BridgeBootstrap& globals() const { return globals_; }
};

#ifdef _WIN32
class BridgeHttpHandle
{
    HINTERNET handle_;
public:
    explicit BridgeHttpHandle(HINTERNET handle) : handle_(handle) {}
    ~BridgeHttpHandle() { if (handle_) WinHttpCloseHandle(handle_); }
    BridgeHttpHandle(const BridgeHttpHandle&)=delete;
    BridgeHttpHandle& operator=(const BridgeHttpHandle&)=delete;
    HINTERNET get() const { return handle_; }
};
inline bool bridge_fetch(const BridgeConfig& config, BridgeBootstrap& result, unsigned* http_status=nullptr)
{
    if(http_status) *http_status=0;
    const auto deadline=GetTickCount64()+2000;
    // No proxy, redirects, remote host, credential-bearing URLs, request body,
    // or mutations. IO runs exclusively on the adapter worker thread.
    if (!config.port || config.port>65535 || config.token.size()<32 || config.token.size()>256 ||
        config.token.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
        return false;
    BridgeHttpHandle session(WinHttpOpen(L"LostZoneWorldShadow/1",WINHTTP_ACCESS_TYPE_NO_PROXY,
        WINHTTP_NO_PROXY_NAME,WINHTTP_NO_PROXY_BYPASS,0));
    if (!session.get() || !WinHttpSetTimeouts(session.get(),500,500,500,500)) return false;
    BridgeHttpHandle connection(WinHttpConnect(session.get(),L"127.0.0.1",INTERNET_PORT(config.port),0));
    BridgeHttpHandle request(connection.get() ? WinHttpOpenRequest(connection.get(),L"GET",L"/v1/engine-bootstrap",nullptr,
        WINHTTP_NO_REFERER,WINHTTP_DEFAULT_ACCEPT_TYPES,0) : nullptr);
    if (!request.get()) return false;
    DWORD redirect=WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
    if (!WinHttpSetOption(request.get(),WINHTTP_OPTION_REDIRECT_POLICY,&redirect,sizeof(redirect))) return false;
    std::wstring header=L"Authorization: Bearer ";
    header.append(config.token.begin(),config.token.end());header+=L"\r\n";
    if (!WinHttpSendRequest(request.get(),header.c_str(),DWORD(header.size()),WINHTTP_NO_REQUEST_DATA,0,0,0) ||
        !WinHttpReceiveResponse(request.get(),nullptr)) return false;
    DWORD status=0,bytes=sizeof(status);
    if (!WinHttpQueryHeaders(request.get(),WINHTTP_QUERY_STATUS_CODE|WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,&status,&bytes,WINHTTP_NO_HEADER_INDEX)) return false;
    if(http_status) *http_status=status;
    if(status!=200) return false;
    std::string response;
    char buffer[4096];DWORD got=0;
    do
    {
        if (GetTickCount64()>deadline) return false;
        if (!WinHttpReadData(request.get(),buffer,sizeof(buffer),&got)) return false;
        response.append(buffer,got);
        if (response.size()>65536) return false;
    } while (got);
    try { result=parse_bridge_globals(response);return true; }
    catch (const std::exception&) { return false; }
}
#endif
} // namespace netcoop_world

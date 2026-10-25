#pragma once

// Private to exception-enabled bridge workers. Trusted location credentials
// never cross the Lua/client boundary. This transport alone grants no spawn.
#include "netcoop_world_bridge.h"

namespace netcoop_world
{
struct WriterConfig
{
    unsigned port=0;
    std::uint64_t world=0,seed=0;
    std::string token,actor,location;

    static WriterConfig parse(const std::string& encoded, const std::string& map)
    {
        const auto body=bridge_json(encoded,4096);
        if (!body.is_object() || body.size()!=9 || bridge_unsigned(body,"schema")!=1 ||
            !body.contains("mode") || body["mode"]!="writer" ||
            !body.contains("host") || body["host"]!="127.0.0.1")
            throw std::invalid_argument("invalid location writer config");
        WriterConfig result;
        result.location=bridge_identifier(body,"location");
        result.actor=bridge_identifier(body,"actor");
        if (map.empty() || map.size()>64 ||
            map.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")!=std::string::npos ||
            result.location!=map || result.actor!="location:"+map)
            throw std::invalid_argument("writer config belongs to another map");
        const auto port=bridge_unsigned(body,"port");
        if (!port || port>65535 || !body.contains("token") || !body["token"].is_string())
            throw std::invalid_argument("invalid writer endpoint");
        result.port=unsigned(port);
        result.token=body["token"].get<std::string>();
        if (result.token.size()<32 || result.token.size()>256 ||
            result.token.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
            throw std::invalid_argument("invalid writer credential");
        result.world=bridge_unsigned(body,"master_world_id");
        result.seed=bridge_unsigned(body,"master_world_seed");
        if (!result.world) throw std::invalid_argument("invalid writer world identity");
        return result;
    }
};

inline bool writer_instance_valid(const std::string& instance)
{
    return instance.size()==32 && instance.find_first_not_of("0123456789abcdef")==std::string::npos;
}

#ifdef _WIN32
// Worker-thread only. No proxy/redirect/remote address and no unbounded IO.
// A command binds the expected world, seed and master epoch in that SAME
// request; a preceding clock probe is not enough to authorize a mutation.
inline bool writer_request(const WriterConfig& config, const std::string& instance,
                           std::uint64_t epoch, const std::string& method,
                           const std::string& path, const std::string& payload,
                           BridgeJson& result, unsigned& status)
{
    result=BridgeJson();status=0;
    if (!writer_instance_valid(instance) || !config.port || config.port>65535 || !config.world ||
        config.token.size()<32 || config.token.size()>256 ||
        config.token.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos ||
        (method!="GET" && method!="POST") || path.size()>1024 ||
        path.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/?:&=.%")!=std::string::npos ||
        payload.size()>64*1024)
        return false;
    if (method=="POST")
    {
        if (!epoch || path!="/v1/command") return false;
        const auto command=bridge_json(payload,64*1024);
        if (!command.is_object() || command.size()!=3 || !command.contains("arguments") ||
            !command["arguments"].is_object()) return false;
        bridge_identifier(command,"command_id",true);
        const auto operation=bridge_identifier(command,"operation");
        // Administrative planning reaches the master only as an in-game
        // administrator's typed world order (admin_relay), never as a raw
        // administrative operation.
        if (operation!="location_claim" && operation!="location_renew" && operation!="location_recover" &&
            operation!="admin_relay" &&
            operation!="entity_create" && operation!="entity_update" && operation!="entity_death" &&
            operation!="item_create" && operation!="item_move" && operation!="transfer_prepare" &&
            operation!="transfer_claim" && operation!="transfer_commit" && operation!="transfer_abort" &&
            operation!="session_disconnect" && operation!="session_resume" &&
            operation!="native_save_begin" && operation!="native_save_append" &&
            operation!="native_save_finish" && operation!="native_save_cancel" &&
            operation!="account_list" && operation!="account_put") return false;
    }
    else if (!payload.empty() || (path!="/v1/engine-bootstrap" && path!="/v1/clock" &&
             path.rfind("/v1/location?",0)!=0 && path.rfind("/v1/location-bootstrap?",0)!=0 &&
             path.rfind("/v1/transfer?",0)!=0 && path.rfind("/v1/player-save?",0)!=0 &&
             path.rfind("/v1/player-admission?",0)!=0)) return false;
    // Checkpoint reads must bind world/seed/epoch in the same request too.
    if ((path.rfind("/v1/player-save?",0)==0 || path.rfind("/v1/player-admission?",0)==0) && !epoch) return false;
    const auto deadline=GetTickCount64()+2000;
    BridgeHttpHandle session(WinHttpOpen(L"LostZoneWorldWriter/1",WINHTTP_ACCESS_TYPE_NO_PROXY,
        WINHTTP_NO_PROXY_NAME,WINHTTP_NO_PROXY_BYPASS,0));
    if (!session.get() || !WinHttpSetTimeouts(session.get(),500,500,500,500)) return false;
    BridgeHttpHandle connection(WinHttpConnect(session.get(),L"127.0.0.1",INTERNET_PORT(config.port),0));
    const std::wstring verb(method.begin(),method.end()), resource(path.begin(),path.end());
    BridgeHttpHandle request(connection.get() ? WinHttpOpenRequest(connection.get(),verb.c_str(),resource.c_str(),nullptr,
        WINHTTP_NO_REFERER,WINHTTP_DEFAULT_ACCEPT_TYPES,0) : nullptr);
    if (!request.get()) return false;
    DWORD redirect=WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
    if (!WinHttpSetOption(request.get(),WINHTTP_OPTION_REDIRECT_POLICY,&redirect,sizeof(redirect))) return false;
    std::wstring header=L"Authorization: Bearer ";
    header.append(config.token.begin(),config.token.end());
    header+=L"\r\nX-LostZone-Instance: ";header.append(instance.begin(),instance.end());
    if (epoch)
    {
        const auto binding=std::to_string(config.world)+":"+std::to_string(config.seed)+":"+std::to_string(epoch);
        header+=L"\r\nX-LostZone-World: ";header.append(binding.begin(),binding.end());
    }
    header+=L"\r\nContent-Type: application/json\r\n";
    if (!WinHttpSendRequest(request.get(),header.c_str(),DWORD(header.size()),
        payload.empty() ? WINHTTP_NO_REQUEST_DATA:const_cast<char*>(payload.data()),
        DWORD(payload.size()),DWORD(payload.size()),0) || !WinHttpReceiveResponse(request.get(),nullptr)) return false;
    DWORD code=0,bytes=sizeof(code);
    if (!WinHttpQueryHeaders(request.get(),WINHTTP_QUERY_STATUS_CODE|WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,&code,&bytes,WINHTTP_NO_HEADER_INDEX)) return false;
    status=unsigned(code);
    if (status!=200) return false; // Never pass private/error response text upward.
    // The master always sends a bounded Content-Length. A 200 header alone
    // does not acknowledge a command: the connection may end mid-response.
    DWORD expected=0;bytes=sizeof(expected);
    if (!WinHttpQueryHeaders(request.get(),WINHTTP_QUERY_CONTENT_LENGTH|WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,&expected,&bytes,WINHTTP_NO_HEADER_INDEX) ||
        !expected || expected>2*1024*1024) return false;
    std::string response;
    char buffer[4096];DWORD got=0;
    do
    {
        if (GetTickCount64()>deadline || !WinHttpReadData(request.get(),buffer,sizeof(buffer),&got))
        { status=0;return false; } // Retry the SAME command, including a lost Finish.
        response.append(buffer,got);
        if (response.size()>expected) return false;
    } while (got);
    if (response.size()!=expected) { status=0;return false; }
    try
    {
        auto body=bridge_json(response,2*1024*1024);
        if (!body.is_object() || body.size()!=1 || !body.contains("result") || !body["result"].is_object()) return false;
        result=std::move(body["result"]);
    }
    catch (const std::exception&) { return false; } // Invalid protocol must not escape the IO worker.
    return true;
}
#endif
}

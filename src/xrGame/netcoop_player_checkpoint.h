#pragma once

// Private to exception-enabled IO workers. No engine objects, Lua, credentials
// or gameplay activation here. The caller owns admission and durable cursor IO.
#include "netcoop_world_writer.h"
#include <algorithm>
#include <functional>
#include <vector>
#ifdef _WIN32
#include <bcrypt.h>
#pragma comment(lib,"bcrypt.lib")
#endif

namespace netcoop_world
{
constexpr std::size_t checkpoint_limit=20*1024*1024, checkpoint_chunk=30720;

inline std::string checkpoint_base64(const std::string& raw)
{
    if (raw.size()>checkpoint_limit) throw std::invalid_argument("checkpoint encoding budget");
    static const char table[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;out.reserve((raw.size()+2)/3*4);
    for (std::size_t i=0;i<raw.size();i+=3)
    {
        const auto a=static_cast<unsigned char>(raw[i]);
        const unsigned b=i+1<raw.size() ? static_cast<unsigned char>(raw[i+1]):0;
        const unsigned c=i+2<raw.size() ? static_cast<unsigned char>(raw[i+2]):0;
        out+=table[a>>2];out+=table[((a&3)<<4)|(b>>4)];
        out+=i+1<raw.size() ? table[((b&15)<<2)|(c>>6)]:'=';
        out+=i+2<raw.size() ? table[c&63]:'=';
    }
    return out;
}

inline std::string checkpoint_unbase64(const std::string& encoded,std::size_t limit=checkpoint_chunk)
{
    if (limit>checkpoint_limit || encoded.size()%4 || encoded.size()>(limit+2)/3*4)
        throw std::invalid_argument("checkpoint base64 budget");
    auto value=[](char c)->unsigned {
        if (c>='A' && c<='Z') return unsigned(c-'A');
        if (c>='a' && c<='z') return unsigned(c-'a'+26);
        if (c>='0' && c<='9') return unsigned(c-'0'+52);
        if (c=='+') return 62;
        if (c=='/') return 63;
        throw std::invalid_argument("invalid checkpoint base64");
    };
    std::string out;out.reserve(encoded.size()/4*3);
    for (std::size_t i=0;i<encoded.size();i+=4)
    {
        const unsigned a=value(encoded[i]),b=value(encoded[i+1]);
        out+=char((a<<2)|(b>>4));
        if (encoded[i+2]=='=')
        {
            if (i+4!=encoded.size() || encoded[i+3]!='=' || (b&15))
                throw std::invalid_argument("noncanonical checkpoint base64");
        }
        else
        {
            const unsigned c=value(encoded[i+2]);out+=char((b<<4)|(c>>2));
            if (encoded[i+3]=='=')
            {
                if (i+4!=encoded.size() || (c&3)) throw std::invalid_argument("noncanonical checkpoint base64");
            }
            else out+=char((c<<6)|value(encoded[i+3]));
        }
    }
    if (out.size()>limit) throw std::invalid_argument("decoded checkpoint budget");
    return out;
}

inline bool checkpoint_hex(const std::string& value,std::size_t count)
{
    return value.size()==count && value.find_first_not_of("0123456789abcdef")==std::string::npos;
}

#ifdef _WIN32
inline std::string checkpoint_digest(const std::string& raw,LPCWSTR algorithm,std::size_t bytes)
{
    if (raw.size()>checkpoint_limit+1024) throw std::invalid_argument("checkpoint hash budget");
    struct Algorithm { BCRYPT_ALG_HANDLE h=nullptr;~Algorithm(){if(h) BCryptCloseAlgorithmProvider(h,0);} } alg;
    struct Hash { BCRYPT_HASH_HANDLE h=nullptr;~Hash(){if(h) BCryptDestroyHash(h);} };
    DWORD object_size=0,hash_size=0,got=0;
    if (BCryptOpenAlgorithmProvider(&alg.h,algorithm,nullptr,0)<0 ||
        BCryptGetProperty(alg.h,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&got,0)<0 ||
        BCryptGetProperty(alg.h,BCRYPT_HASH_LENGTH,reinterpret_cast<PUCHAR>(&hash_size),sizeof(hash_size),&got,0)<0 ||
        hash_size!=bytes || object_size>1024*1024) throw std::runtime_error("checkpoint hash unavailable");
    std::vector<unsigned char> object(object_size),result(bytes);
    Hash hash; // Destroy before its backing object buffer.
    if (BCryptCreateHash(alg.h,&hash.h,object.data(),object_size,nullptr,0,0)<0 ||
        BCryptHashData(hash.h,reinterpret_cast<PUCHAR>(const_cast<char*>(raw.data())),ULONG(raw.size()),0)<0 ||
        BCryptFinishHash(hash.h,result.data(),hash_size,0)<0) throw std::runtime_error("checkpoint hash failed");
    return std::string(result.begin(),result.end());
}

inline std::string checkpoint_hex_bytes(const std::string& bytes)
{
    static const char hex[]="0123456789abcdef";
    std::string out;out.reserve(bytes.size()*2);
    for (unsigned char c:bytes) { out+=hex[c>>4];out+=hex[c&15]; }
    return out;
}

inline std::string checkpoint_sha256(const std::string& raw)
{
    return checkpoint_hex_bytes(checkpoint_digest(raw,BCRYPT_SHA256_ALGORITHM,32));
}

inline std::string checkpoint_player_id(std::uint64_t world,std::uint64_t seed,std::string account,unsigned slot)
{
    if (!world || account.size()<3 || account.size()>20 || slot<1 || slot>10 ||
        account.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")!=std::string::npos)
        throw std::invalid_argument("invalid native player identity");
    for (char& c:account) if (c>='A' && c<='Z') c=char(c-'A'+'a');
    // RFC4122 UUID5 with Python uuid.NAMESPACE_URL, canonical network bytes.
    static const unsigned char ns[]={0x6b,0xa7,0xb8,0x11,0x9d,0xad,0x11,0xd1,0x80,0xb4,0x00,0xc0,0x4f,0xd4,0x30,0xc8};
    std::string name(reinterpret_cast<const char*>(ns),sizeof(ns));
    name+="lostzone:native-player:"+std::to_string(world)+":"+std::to_string(seed)+":"+account+":"+std::to_string(slot);
    auto digest=checkpoint_digest(name,BCRYPT_SHA1_ALGORITHM,20).substr(0,16);
    digest[6]=char((static_cast<unsigned char>(digest[6])&15)|0x50);
    digest[8]=char((static_cast<unsigned char>(digest[8])&63)|0x80);
    return checkpoint_hex_bytes(digest);
}

enum class CheckpointStep { Progress,Retry,Rejected,Complete };
using CheckpointRequest=std::function<bool(const std::string&,const std::string&,const std::string&,BridgeJson&,unsigned&)>;
inline CheckpointStep checkpoint_failure(unsigned status)
{
    // A 200 header without a verified complete body is an ambiguous reply,
    // not a fencing refusal. Retry the SAME idempotent command; never accept it.
    return !status || status==200 || status==408 || status==429 || status>=500 ? CheckpointStep::Retry:CheckpointStep::Rejected;
}
inline bool checkpoint_format(const void* data,std::size_t count)
{
    if(!data || count<4 || count>checkpoint_limit) return false;
    const auto raw=static_cast<const char*>(data);
    return raw[0]=='N' && raw[1]=='C' && raw[2]=='H' && ((raw[3]>='3' && raw[3]<='9') || raw[3]=='A');
}
inline bool checkpoint_format(const std::string& raw) {return checkpoint_format(raw.data(),raw.size());}

enum class PlayerSlotStatus { Missing,Absent,Staged,Active,Disconnected,Elsewhere };
struct PlayerSlotObservation
{
    PlayerSlotStatus state=PlayerSlotStatus::Missing;
    std::string character,sha256;
    std::string home; // Elsewhere: the location the character lives on
    std::uint64_t entity_version=0,session_fence=0,revision=0,bytes=0;

    static PlayerSlotObservation parse(const BridgeJson& body,const WriterConfig& config,std::uint64_t epoch,
        const std::string& account,unsigned slot,std::uint64_t fence)
    {
        const auto character=checkpoint_player_id(config.world,config.seed,account,slot);
        // ELSEWHERE carries one more field, the character's home location.
        const bool elsewhere=body.is_object() && body.contains("status") && body["status"]=="ELSEWHERE";
        if (!body.is_object() || body.size()!=(elsewhere ? 14u : 13u) || bridge_unsigned(body,"schema")!=1 ||
            body.at("world_id")!=std::to_string(config.world) || body.at("seed")!=std::to_string(config.seed) ||
            bridge_unsigned(body,"epoch")!=epoch || bridge_unsigned(body,"fence")!=fence ||
            body.at("location")!=config.location || body.at("account")!=account ||
            body.at("character_id")!=character || bridge_unsigned(body,"slot")!=slot || !epoch || !fence)
            throw std::invalid_argument("native slot scope mismatch");
        constexpr auto maximum=std::uint64_t(0x7fffffffffffffffULL);
        PlayerSlotObservation result;result.character=character;
        result.entity_version=bridge_unsigned(body,"entity_version");
        result.session_fence=bridge_unsigned(body,"session_fence");
        const auto status=body.at("status").get<std::string>();
        if (status=="ABSENT") result.state=PlayerSlotStatus::Absent;
        else if (status=="STAGED") result.state=PlayerSlotStatus::Staged;
        else if (status=="ACTIVE") result.state=PlayerSlotStatus::Active;
        else if (status=="DISCONNECTED") result.state=PlayerSlotStatus::Disconnected;
        else if (status=="ELSEWHERE")
        {
            result.state=PlayerSlotStatus::Elsewhere;
            result.home=body.at("home").get<std::string>();
            bool valid=!result.home.empty() && result.home.size()<=64 && result.home!=config.location;
            for (char c:result.home) valid=valid && ((c>='a' && c<='z') || (c>='0' && c<='9') || c=='_');
            if (!valid) throw std::invalid_argument("native slot home location");
        }
        else throw std::invalid_argument("unsupported native slot state");
        const bool live=result.state==PlayerSlotStatus::Active || result.state==PlayerSlotStatus::Disconnected;
        const auto& checkpoint=body.at("checkpoint");
        if (live ? (!result.entity_version || result.entity_version>maximum || !result.session_fence || result.session_fence>maximum):
            (result.entity_version || result.session_fence || !checkpoint.is_null()))
            throw std::invalid_argument("native slot version mismatch");
        if (!checkpoint.is_null())
        {
            if (!checkpoint.is_object() || checkpoint.size()!=3) throw std::invalid_argument("native slot checkpoint shape");
            result.revision=bridge_unsigned(checkpoint,"revision");result.bytes=bridge_unsigned(checkpoint,"bytes");
            result.sha256=checkpoint.at("sha256").get<std::string>();
            if (!result.revision || result.revision>maximum || result.bytes<4 || result.bytes>checkpoint_limit ||
                !checkpoint_hex(result.sha256,64)) throw std::invalid_argument("native slot checkpoint bounds");
        }
        return result;
    }
};

// IO worker only: an observation is never permission to spawn/resume. Every
// later command/read still validates live authority, session and CAS versions.
inline CheckpointStep inspect_player_slot(const WriterConfig& config,const std::string& instance,std::uint64_t epoch,
    std::string account,unsigned slot,std::uint64_t fence,PlayerSlotObservation& output,unsigned& status)
{
    output={};status=0;
    try
    {
        checkpoint_player_id(config.world,config.seed,account,slot); // Validate before building a URL.
        if (!epoch || epoch>0x7fffffffffffffffULL || !fence || fence>0x7fffffffffffffffULL) return CheckpointStep::Rejected;
        for (char& c:account) if (c>='A' && c<='Z') c=char(c-'A'+'a');
        const auto path="/v1/player-admission?account="+account+"&slot="+std::to_string(slot)+"&location="+config.location+
            "&fence="+std::to_string(fence)+"&epoch="+std::to_string(epoch);
        BridgeJson body;
        if (!writer_request(config,instance,epoch,"GET",path,"",body,status)) return checkpoint_failure(status);
        output=PlayerSlotObservation::parse(body,config,epoch,account,slot,fence);
        return CheckpointStep::Complete;
    }
    catch (const std::exception&) {output={};return CheckpointStep::Rejected;}
}

// One request per step, so an IO worker can renew leases and serve other
// players between chunks. Retried steps keep exactly the same command ID.
class CheckpointUpload
{
    std::string raw_,character_,sha_,transaction_,binding_,upload_;
    std::uint64_t fence_,session_,version_,revision_;
    unsigned slot_,phase_=0;
    std::size_t offset_=0;
    BridgeJson durable_;
    BridgeJson scope() const { return {{"character_id",character_},{"fence",fence_},{"session_fence",session_}}; }
public:
    CheckpointUpload(std::string raw,std::string character,std::uint64_t fence,std::uint64_t session,
        std::uint64_t version,std::uint64_t revision,unsigned slot,std::string transaction)
        :raw_(std::move(raw)),character_(std::move(character)),transaction_(std::move(transaction)),
         fence_(fence),session_(session),version_(version),revision_(revision),slot_(slot)
    {
        constexpr auto maximum=std::uint64_t(0x7fffffffffffffffULL);
        if (!checkpoint_format(raw_) || !checkpoint_hex(character_,32) || !checkpoint_hex(transaction_,32) ||
            !fence_ || fence_>maximum || !session_ || session_>maximum || !version_ || version_>=maximum ||
            revision_>=maximum || slot_<1 || slot_>10) throw std::invalid_argument("invalid checkpoint upload");
        sha_=checkpoint_sha256(raw_);
        auto bound=scope();bound["version"]=version_;bound["revision"]=revision_;bound["slot"]=slot_;
        bound["sha256"]=sha_;bound["bytes"]=raw_.size();bound["transaction"]=transaction_;
        binding_=checkpoint_sha256(bound.dump());
    }
    BridgeJson cursor() const { return {{"schema",1},{"binding",binding_},{"phase",phase_},{"upload_id",upload_},{"offset",offset_}}; }
    void restore_cursor(const BridgeJson& value)
    {
        if (!value.is_object() || value.size()!=5 || bridge_unsigned(value,"schema")!=1 ||
            !value.contains("binding") || value["binding"]!=binding_ || !value.contains("upload_id") || !value["upload_id"].is_string())
            throw std::invalid_argument("checkpoint cursor identity changed");
        const auto phase=bridge_unsigned(value,"phase"),offset=bridge_unsigned(value,"offset");
        const auto upload=value["upload_id"].get<std::string>();
        if (phase>3 || offset>raw_.size() || (phase==0 && (!upload.empty() || offset)) ||
            (phase && !checkpoint_hex(upload,32)) || (phase==1 && (offset%checkpoint_chunk || offset>=raw_.size())) ||
            (phase>=2 && offset!=raw_.size())) throw std::invalid_argument("invalid checkpoint cursor");
        // A cursor is not durable proof: replay Finish after process recovery.
        phase_=unsigned(phase==3 ? 2:phase);offset_=std::size_t(offset);upload_=upload;durable_=BridgeJson();
    }
    CheckpointStep step(const CheckpointRequest& request)
    {
        if (phase_==3) return CheckpointStep::Complete;
        auto args=scope();std::string operation;
        std::size_t next=offset_;
        if (!phase_)
        {
            operation="native_save_begin";args["entity_version"]=version_;args["base_revision"]=revision_;
            args["slot"]=slot_;args["byte_count"]=raw_.size();args["sha256"]=sha_;
        }
        else
        {
            args["upload_id"]=upload_;
            if (phase_==1)
            {
                operation="native_save_append";next=offset_+std::min(checkpoint_chunk,raw_.size()-offset_);
                args["offset"]=offset_;args["data"]=checkpoint_base64(raw_.substr(offset_,next-offset_));
            }
            else operation="native_save_finish";
        }
        const auto id=checkpoint_sha256(transaction_+":"+operation+":"+std::to_string(offset_)).substr(0,32);
        const auto payload=BridgeJson{{"command_id",id},{"operation",operation},{"arguments",args}}.dump();
        if (payload.size()>65536) throw std::invalid_argument("checkpoint request budget");
        BridgeJson result;unsigned status=0;
        if (!request("POST","/v1/command",payload,result,status)) return checkpoint_failure(status);
        try
        {
            if (!result.is_object()) return CheckpointStep::Rejected;
            if (!phase_)
            {
                const auto upload=bridge_identifier(result,"upload_id",true);
                if (!checkpoint_hex(upload,32) || bridge_unsigned(result,"offset") ||
                    bridge_unsigned(result,"chunk_bytes")!=checkpoint_chunk) return CheckpointStep::Rejected;
                upload_=upload;phase_=1;
            }
            else if (phase_==1)
            {
                if (!result.contains("upload_id") || result["upload_id"]!=upload_ || bridge_unsigned(result,"offset")!=next)
                    return CheckpointStep::Rejected;
                offset_=next;if(offset_==raw_.size()) phase_=2;
            }
            else
            {
                if (!result.contains("character_id") || result["character_id"]!=character_ ||
                    !result.contains("durable") || result["durable"]!=true || !result.contains("sha256") || result["sha256"]!=sha_ ||
                    bridge_unsigned(result,"revision")!=revision_+1 || bridge_unsigned(result,"entity_version")!=version_+1 ||
                    bridge_unsigned(result,"bytes")!=raw_.size()) return CheckpointStep::Rejected;
                durable_=std::move(result);phase_=3;return CheckpointStep::Complete;
            }
        }
        catch (const std::exception&) { return CheckpointStep::Rejected; }
        return CheckpointStep::Progress;
    }
    const BridgeJson& durable() const
    { if (phase_!=3) throw std::logic_error("checkpoint is not durable");return durable_; }
};

class CheckpointDownload
{
    std::string path_,sha_,raw_;
    std::uint64_t revision_;
    std::size_t bytes_,offset_=0;
    bool complete_=false,rejected_=false;
public:
    CheckpointDownload(std::string character,std::uint64_t fence,std::uint64_t session,std::uint64_t revision,
        std::string sha,std::size_t bytes,std::string transfer="") :sha_(std::move(sha)),revision_(revision),bytes_(bytes)
    {
        constexpr auto maximum=std::uint64_t(0x7fffffffffffffffULL);
        if (!checkpoint_hex(character,32) || !fence || fence>maximum || !session || session>maximum ||
            !revision || revision>maximum || !checkpoint_hex(sha_,64) || bytes<4 || bytes>checkpoint_limit ||
            (!transfer.empty() && !checkpoint_hex(transfer,32))) throw std::invalid_argument("invalid checkpoint read");
        path_="/v1/player-save?character_id="+character+"&fence="+std::to_string(fence)+
            "&session_fence="+std::to_string(session)+"&revision="+std::to_string(revision);
        if (!transfer.empty()) path_+="&transfer_id="+transfer;
        raw_.reserve(bytes);
    }
    CheckpointStep step(const CheckpointRequest& request)
    {
        if (rejected_) return CheckpointStep::Rejected;
        if (complete_) return CheckpointStep::Complete;
        BridgeJson result;unsigned status=0;
        if (!request("GET",path_+"&offset="+std::to_string(offset_),"",result,status)) return checkpoint_failure(status);
        try
        {
            const auto next=offset_+std::min(checkpoint_chunk,bytes_-offset_);
            if (!result.is_object() || bridge_unsigned(result,"revision")!=revision_ ||
                bridge_unsigned(result,"bytes")!=bytes_ || bridge_unsigned(result,"offset")!=offset_ ||
                bridge_unsigned(result,"next_offset")!=next || !result.contains("sha256") || result["sha256"]!=sha_ ||
                !result.contains("data") || !result["data"].is_string()) return CheckpointStep::Rejected;
            const auto chunk=checkpoint_unbase64(result["data"].get<std::string>());
            if (chunk.size()!=next-offset_) return CheckpointStep::Rejected;
            raw_+=chunk;offset_=next;
            if (offset_==bytes_)
            {
                if (!checkpoint_format(raw_) || checkpoint_sha256(raw_)!=sha_)
                { raw_.clear();rejected_=true;return CheckpointStep::Rejected; }
                complete_=true;return CheckpointStep::Complete;
            }
        }
        catch (const std::exception&) { return CheckpointStep::Rejected; }
        return CheckpointStep::Progress;
    }
    const std::string& bytes() const
    { if (!complete_) throw std::logic_error("checkpoint read is incomplete");return raw_; }
};
#endif
}

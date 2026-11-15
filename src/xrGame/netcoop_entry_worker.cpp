// Exception-enabled transport boundary: no engine/PCH, Lua or ALife access.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "netcoop_entry_worker.h"
#include <windows.h>
#include <winhttp.h>
#include <algorithm>
#include <cctype>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include "../3rd party/nlohmann/json.hpp"

namespace netcoop_world
{
namespace
{
struct InternetHandle
{
    HINTERNET value;
    explicit InternetHandle(HINTERNET handle):value(handle) {}
    ~InternetHandle(){if(value) WinHttpCloseHandle(value);}
    InternetHandle(const InternetHandle&)=delete;
    InternetHandle& operator=(const InternetHandle&)=delete;
};
bool login_valid(const char* account)
{
    if (!account || std::strlen(account)<3 || std::strlen(account)>20) return false;
    for (const char* c=account;*c;++c)
        if (!((*c>='a' && *c<='z') || (*c>='A' && *c<='Z') || (*c>='0' && *c<='9') || *c=='_' || *c=='.' || *c=='-')) return false;
    return true;
}
static std::string master_entry_query(HINTERNET session, const char* address, const char* account, int slot)
{
	char answer[256]{};
	if (!address || std::strlen(address) > 200) return answer;
	std::string text = address, host;
	unsigned port = 5446;
	const size_t colon = text.rfind(':');
	if (colon != std::string::npos)
	{
		host = text.substr(0, colon);
		const auto digits=text.substr(colon+1);
		if(digits.empty() || digits.size()>5 || digits.find_first_not_of("0123456789")!=std::string::npos) return answer;
		port = unsigned(std::stoul(digits));
	}
	else host = text;
	auto valid_host = [](const std::string& value)
	{
		// Bound the formatted route as well as the DNS name: it crosses a 256-byte ABI.
		if (value.empty() || value.size() > 200) return false;
		for (char c : value)
			if (!isalnum(static_cast<unsigned char>(c)) && c != '.' && c != '-') return false;
		return true;
	};
	if (!valid_host(host) || port < 1 || port > 65535) return answer;
	std::wstring wide(host.begin(), host.end());
	if (!session) return answer;
	const ULONGLONG deadline=GetTickCount64()+2000;
	InternetHandle connection(WinHttpConnect(session, wide.c_str(), INTERNET_PORT(port), 0));
	// The login is a public name (letters, digits, _ . -): no escaping needed.
	std::wstring path = L"/v1/entry";
	if (account && login_valid(account) && slot >= 0 && slot <= 10)
	{
		path += L"?account=";
		for (const char* c = account; *c; ++c) path += wchar_t(*c);
		path += L"&slot=" + std::to_wstring(slot);
	}
	InternetHandle request(connection.value ? WinHttpOpenRequest(connection.value, L"GET", path.c_str(), nullptr,
		WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0) : nullptr);
	DWORD redirect=WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
	if (!request.value || !WinHttpSetOption(request.value,WINHTTP_OPTION_REDIRECT_POLICY,&redirect,sizeof(redirect))) return answer;
	std::string body;
	bool complete=false;
	DWORD status = 0, size = sizeof(status), expected=0;
	if (WinHttpSendRequest(request.value, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
		WinHttpReceiveResponse(request.value, nullptr) &&
		WinHttpQueryHeaders(request.value, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX,
			&status, &size, WINHTTP_NO_HEADER_INDEX) && (status == 200 || status==503))
	{
		size=sizeof(expected);
		if(!WinHttpQueryHeaders(request.value,WINHTTP_QUERY_CONTENT_LENGTH|WINHTTP_QUERY_FLAG_NUMBER,
			WINHTTP_HEADER_NAME_BY_INDEX,&expected,&size,WINHTTP_NO_HEADER_INDEX) || !expected || expected>=4096) return answer;
		char buffer[1024];
		DWORD read = 0;
		while (body.size() < 4096 && GetTickCount64()<deadline && WinHttpReadData(request.value, buffer, sizeof(buffer), &read))
		{
			if (!read) {complete=true;break;}
			body.append(buffer,read);
		}
	}
	if (!complete || body.empty() || body.size()!=expected || body.size() >= 4096) {strcpy_s(answer,"wait|master_unavailable||3");return answer;}
	try
	{
		const auto entry = nlohmann::json::parse(body,[](int depth,nlohmann::json::parse_event_t,nlohmann::json&){
			if(depth>32) throw std::invalid_argument("entry nesting budget");return true;
		});
		if (!entry.is_object() || !entry.contains("schema") || entry["schema"]!=1) return answer;
		if(status==503) {
			const auto state=entry.value("state",std::string("recovering")),location=entry.value("location",std::string());
			if(state.size()>32 || location.size()>64 || state.find_first_not_of("abcdefghijklmnopqrstuvwxyz_")!=std::string::npos || location.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos) return answer;
			const bool terminal=state=="disabled" || state=="failed" || state=="unplanned" || state=="control_error";
			sprintf_s(answer,"%s|%s|%s|%d",terminal ? "error":"wait",state.c_str(),location.c_str(),std::max(1,std::min(30,entry.value("retry_seconds",3))));
			return answer;
		}
		const std::string target = entry.value("host", std::string());
		if(!entry.contains("port") || !entry["port"].is_number_unsigned()) return answer;
		const auto target_port = entry["port"].get<unsigned long long>();
		const std::string location = entry.value("location", std::string());
		if(location.size()>64 || location.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos) return answer;
		if (target_port < 1 || target_port > 65535 || (!target.empty() && !valid_host(target))) return answer;
		// No host of its own: the location runs on the master's machine.
		sprintf_s(answer, "%s:%u", target.empty() ? host.c_str() : target.c_str(), unsigned(target_port));
	}
	catch (...) { answer[0] = 0; }
	return answer;
}

struct ClientEntryWorker
{
    struct Request {std::string address,account;int slot=0;};
    std::mutex lock;
    std::condition_variable wake;
    std::thread thread;
    bool stopping=false,pending=false,done=true;
    Request queued;
    std::string identity,result;
    ULONGLONG completed=0;
    void run() noexcept {
        // One anonymous HTTP session and one thread for this menu lifetime.
        // Never create a new OS thread/session on every route retry.
        InternetHandle session(nullptr);
        for (;;) {
            Request request;
            {
                std::unique_lock<std::mutex> guard(lock);
                wake.wait(guard,[this]{return stopping || pending;});
                if(stopping) return;
                request=std::move(queued);pending=false;
            }
            try {
                if(!session.value) {
                    session.value=WinHttpOpen(L"LostZone/1.0",WINHTTP_ACCESS_TYPE_NO_PROXY,
                        WINHTTP_NO_PROXY_NAME,WINHTTP_NO_PROXY_BYPASS,0);
                    if(session.value && !WinHttpSetTimeouts(session.value,500,500,500,500)) {
                        WinHttpCloseHandle(session.value);session.value=nullptr;
                    }
                }
                auto reply=master_entry_query(session.value,request.address.c_str(),request.account.c_str(),request.slot);
                if(reply.empty()) reply="wait|master_unavailable||3";
                std::lock_guard<std::mutex> guard(lock);
                result=std::move(reply);completed=GetTickCount64();done=true;
            } catch (...) {
                // Includes allocation/transport/parser failures. A future poll
                // may retry; the thread must not terminate the whole process.
                std::lock_guard<std::mutex> guard(lock);result.clear();completed=0;done=true;
            }
        }
    }
    void stop() {
        std::thread joining;
        {
            std::lock_guard<std::mutex> guard(lock);stopping=true;joining=std::move(thread);
        }
        wake.notify_all();
        if(joining.joinable()) joining.join();
        std::lock_guard<std::mutex> guard(lock);
        stopping=false;pending=false;done=true;queued={};identity.clear();result.clear();completed=0;
    }
    ~ClientEntryWorker(){stop();}
    std::string poll(const std::string& address,const std::string& account,int slot) {
        const auto id=address+"/"+account+"/"+std::to_string(slot);
        Request request{address,account,slot};
        std::lock_guard<std::mutex> guard(lock);
        if(!done) return "wait|contacting||1";
        if(identity==id && !result.empty() && GetTickCount64()-completed<3000) return result;
        if(!thread.joinable()) thread=std::thread([this]{run();});
        identity=id;queued=std::move(request);pending=true;done=false;
        wake.notify_all();
        return "wait|contacting||1";
    }
};
static ClientEntryWorker& client_entry_worker() {static ClientEntryWorker worker;return worker;}
} // namespace

void poll_entry_route(const char* address,const char* account,int slot,char* answer,std::size_t capacity) noexcept
{
    if (!answer || !capacity) return;
    answer[0]=0;
    if (!address || std::strlen(address)>200 || (account && std::strlen(account)>64) || slot<0 || slot>10) return;
    try {
        const auto result=client_entry_worker().poll(address,account ? account:"",slot);
        if (result.size()<capacity) std::memcpy(answer,result.c_str(),result.size()+1);
    } catch (...) {
        const char failure[]="wait|master_unavailable||3";
        if (sizeof(failure)<=capacity) std::memcpy(answer,failure,sizeof(failure));
    }
}
void stop_entry_route() noexcept
{
    try {client_entry_worker().stop();} catch (...) {}
}
} // namespace netcoop_world

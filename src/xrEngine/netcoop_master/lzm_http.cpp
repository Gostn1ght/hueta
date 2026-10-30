#include "lzm_http.h"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <chrono>

#pragma comment(lib, "ws2_32.lib")

namespace lzm
{
std::vector<std::string> HttpRequest::all(const std::string& name) const
{
    std::vector<std::string> out;
    for (auto& h : headers)
        if (h.first == name) out.push_back(h.second);
    return out;
}

std::optional<std::string> HttpRequest::header(const std::string& name) const
{
    for (auto& h : headers)
        if (h.first == name) return h.second;
    return std::nullopt;
}

std::string HttpRequest::content_type() const
{
    auto value = header("content-type");
    if (!value) return "text/plain";
    std::string main = lower(trim(split(*value, ';')[0]));
    if (std::count(main.begin(), main.end(), '/') != 1) return "text/plain";
    return main;
}

const char* http_reason(int status)
{
    switch (status)
    {
    case 200: return "OK";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 405: return "Method Not Allowed";
    case 409: return "Conflict";
    case 413: return "Request Entity Too Large";
    case 414: return "Request-URI Too Long";
    case 429: return "Too Many Requests";
    case 431: return "Request Header Fields Too Large";
    case 501: return "Not Implemented";
    case 503: return "Service Unavailable";
    default: return "Unknown";
    }
}

static std::string unquote_plus(const std::string& text)
{
    std::string out;
    for (size_t i = 0; i < text.size(); ++i)
    {
        char c = text[i];
        if (c == '+') out += ' ';
        else if (c == '%' && i + 2 < text.size() && isxdigit((unsigned char)text[i + 1]) && isxdigit((unsigned char)text[i + 2]))
        {
            out += char(std::stoi(text.substr(i + 1, 2), nullptr, 16));
            i += 2;
        }
        else out += c;
    }
    return out;
}

std::map<std::string, std::vector<std::string>> parse_qs(const std::string& query, bool keep_blank, int max_fields)
{
    std::map<std::string, std::vector<std::string>> result;
    if (max_fields >= 0 && max_fields < int(1 + std::count(query.begin(), query.end(), '&')))
        throw Invalid("Max number of fields exceeded");
    if (query.empty()) return result;
    for (auto& field : split(query, '&'))
    {
        size_t eq = field.find('=');
        if (eq == std::string::npos) throw Invalid("bad query field");
        std::string name = field.substr(0, eq), value = field.substr(eq + 1);
        if (!value.empty() || keep_blank) result[unquote_plus(name)].push_back(unquote_plus(value));
    }
    return result;
}

static std::once_flag s_wsa;

HttpServer::HttpServer(const std::string& bind_address, int port, size_t workers, HttpHandler handler, bool http11, const char* server_name)
    : workers_(workers), handler_(std::move(handler)), http11_(http11), server_name_(server_name)
{
    std::call_once(s_wsa, [] { WSADATA data; WSAStartup(MAKEWORD(2, 2), &data); });
    SOCKET s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) throw Unavailable("socket failed");
    // Python's HTTPServer sets SO_REUSEADDR; on Windows exclusive use keeps a
    // second master from sharing the port instead.
    BOOL exclusive = TRUE;
    setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char*)&exclusive, sizeof(exclusive));
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(u_short(port));
    inet_pton(AF_INET, bind_address.c_str(), &address.sin_addr);
    if (::bind(s, (sockaddr*)&address, sizeof(address)) != 0 || ::listen(s, 64) != 0)
    {
        closesocket(s);
        throw Unavailable(format("port %d is already in use", port));
    }
    int length = sizeof(address);
    getsockname(s, (sockaddr*)&address, &length);
    port_ = ntohs(address.sin_port);
    socket_ = uintptr_t(s);
    accept_ = std::thread([this] { loop(); });
}

HttpServer::~HttpServer() { stop(); }

void HttpServer::stop()
{
    if (stopping_.exchange(true)) return;
    if (socket_ != ~uintptr_t(0))
    {
        closesocket(SOCKET(socket_));
        socket_ = ~uintptr_t(0);
    }
    if (accept_.joinable()) accept_.join();
    // Request threads finish their transaction (block_on_close in Python).
    for (int i = 0; i < 1000 && busy_.load() > 0; ++i) Sleep(10);
}

void HttpServer::loop()
{
    while (!stopping_)
    {
        sockaddr_in from{};
        int length = sizeof(from);
        SOCKET client = ::accept(SOCKET(socket_), (sockaddr*)&from, &length);
        if (client == INVALID_SOCKET)
        {
            if (stopping_) break;
            Sleep(5);
            continue;
        }
        char text[64] = {};
        inet_ntop(AF_INET, &from.sin_addr, text, sizeof(text));
        if (busy_.load() >= workers_)
        {
            // Overload: drain one header packet so Windows does not reset the
            // client before it reads the 503; no work is done.
            DWORD timeout = 100;
            setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));
            char buffer[4096];
            recv(client, buffer, sizeof(buffer), 0);
            const char* reply = "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
            send(client, reply, int(strlen(reply)), 0);
            shutdown(client, SD_SEND);
            closesocket(client);
            continue;
        }
        ++busy_;
        std::thread([this, client, address = std::string(text)] {
            try { serve(uintptr_t(client), address); }
            catch (...) {}
            closesocket(client);
            --busy_;
        }).detach();
    }
}

static std::string http_date()
{
    SYSTEMTIME t;
    GetSystemTime(&t);
    static const char* days[] = { "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat" };
    static const char* months[] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    return format("%s, %02d %s %04d %02d:%02d:%02d GMT", days[t.wDayOfWeek], t.wDay, months[t.wMonth - 1], t.wYear, t.wHour, t.wMinute, t.wSecond);
}

void HttpServer::serve(uintptr_t handle, std::string address)
{
    SOCKET client = SOCKET(handle);
    DWORD timeout = 8000;
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));
    setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, (const char*)&timeout, sizeof(timeout));
    std::string buffer;
    size_t end = std::string::npos;
    char chunk[8192];
    while ((end = buffer.find("\r\n\r\n")) == std::string::npos)
    {
        if (buffer.size() > 65536 + 100 * 1024) return;
        int n = recv(client, chunk, sizeof(chunk), 0);
        if (n <= 0) return;
        buffer.append(chunk, size_t(n));
    }
    HttpRequest request;
    request.address = address;
    auto lines = split(buffer.substr(0, end), '\n');
    for (auto& line : lines)
        if (!line.empty() && line.back() == '\r') line.pop_back();
    auto respond = [&](const HttpResponse& response) {
        std::string out = std::string(http11_ ? "HTTP/1.1 " : "HTTP/1.0 ") + std::to_string(response.status) + " " + http_reason(response.status) + "\r\n";
        out += "Server: " + server_name_ + "\r\nDate: " + http_date() + "\r\n";
        out += "Content-Type: " + response.content_type + "\r\nContent-Length: " + std::to_string(response.body.size()) + "\r\n";
        out += "Cache-Control: no-store\r\n";
        if (http11_) out += "Connection: close\r\n";
        out += "\r\n" + response.body;
        size_t sent = 0;
        while (sent < out.size())
        {
            int n = send(client, out.data() + sent, int(std::min<size_t>(out.size() - sent, 65536)), 0);
            if (n <= 0) return;
            sent += size_t(n);
        }
        // FIN first, then drain a bounded tail so a refused POST body does not
        // turn into a TCP reset that hides the JSON error (http.py respond()).
        shutdown(client, SD_SEND);
        DWORD shortly = 50;
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, (const char*)&shortly, sizeof(shortly));
        size_t remaining = 65536;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(100);
        while (remaining && std::chrono::steady_clock::now() < deadline)
        {
            int n = recv(client, chunk, int(std::min<size_t>(remaining, 4096)), 0);
            if (n <= 0) break;
            remaining -= size_t(n);
        }
    };
    auto parts = split(lines[0], ' ');
    if (parts.size() != 3 || parts[2].rfind("HTTP/", 0) != 0)
    {
        respond({ 400, "", "text/html;charset=utf-8" });
        return;
    }
    if (lines[0].size() > 65536)
    {
        respond({ 414, "", "text/html;charset=utf-8" });
        return;
    }
    if (lines.size() > 101)
    {
        respond({ 431, "", "text/html;charset=utf-8" });
        return;
    }
    request.method = parts[0];
    request.target = parts[1];
    for (size_t i = 1; i < lines.size(); ++i)
    {
        size_t colon = lines[i].find(':');
        if (colon == std::string::npos) continue;
        request.headers.push_back({ lower(trim(lines[i].substr(0, colon))), trim(lines[i].substr(colon + 1)) });
    }
    // urlsplit: path, then ?query, #fragment dropped.
    std::string target = request.target;
    size_t hash = target.find('#');
    if (hash != std::string::npos) target = target.substr(0, hash);
    size_t q = target.find('?');
    request.path = q == std::string::npos ? target : target.substr(0, q);
    request.query = q == std::string::npos ? "" : target.substr(q + 1);
    std::string leftover = buffer.substr(end + 4);
    auto read_body = [&](size_t length) -> bool {
        request.body = leftover.substr(0, std::min(length, leftover.size()));
        while (request.body.size() < length)
        {
            int n = recv(client, chunk, int(std::min<size_t>(sizeof(chunk), length - request.body.size())), 0);
            if (n <= 0) break;
            request.body.append(chunk, size_t(n));
        }
        request.body_read = true;
        return request.body.size() == length;
    };
    const auto started=GetTickCount64();
    HttpResponse response;
    if (request.method != "GET" && request.method != "POST" && !(request.method == "PUT" || request.method == "DELETE" || request.method == "PATCH"))
        response = { 501, "", "text/html;charset=utf-8" };
    else
        response = handler_(request, read_body);
    static std::atomic<uint64_t> requests{0},errors{0},reported{0},error_at{0};
    ++requests;if(response.status>=400) ++errors;
    const auto finished=GetTickCount64();auto previous=reported.load();
    if(finished-previous>=15000 && reported.compare_exchange_strong(previous,finished))
        log_line(format("[diag][http] requests=%llu errors=%llu sample_ms=%llu",(unsigned long long)requests.exchange(0),(unsigned long long)errors.exchange(0),(unsigned long long)(finished-started)));
    previous=error_at.load();
    if((response.status>=400 || finished-started>500) && finished-previous>=1000 && error_at.compare_exchange_strong(previous,finished)) {
        const char* route="other";
        for(const auto* known:{"/v1/entry","/v1/store","/v1/command","/v1/clock","/v1/engine-bootstrap","/v1/player-admission","/v1/checkpoint"})
            if(request.path==known) route=known;
        log_line(format("[diag][http] route=%s status=%d duration_ms=%llu bytes=%zu",route,response.status,(unsigned long long)(finished-started),request.body.size()));
    }
    respond(response);
}
} // namespace lzm

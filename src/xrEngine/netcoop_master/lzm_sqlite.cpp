#include "lzm_sqlite.h"

#include <windows.h>

namespace lzm
{
namespace
{
typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
constexpr int SQLITE_OK = 0, SQLITE_ROW = 100, SQLITE_DONE = 101;
constexpr int SQLITE_INTEGER = 1, SQLITE_FLOAT = 2, SQLITE_TEXT = 3, SQLITE_BLOB = 4, SQLITE_NULL = 5;
constexpr int OPEN_READONLY = 0x1, OPEN_READWRITE = 0x2, OPEN_CREATE = 0x4, OPEN_FULLMUTEX = 0x10000;

struct Api
{
    int (*open_v2)(const char*, sqlite3**, int, const char*);
    int (*close_v2)(sqlite3*);
    int (*prepare_v2)(sqlite3*, const char*, int, sqlite3_stmt**, const char**);
    int (*finalize)(sqlite3_stmt*);
    int (*step)(sqlite3_stmt*);
    int (*bind_text)(sqlite3_stmt*, int, const char*, int, void (*)(void*));
    int (*bind_blob)(sqlite3_stmt*, int, const void*, int, void (*)(void*));
    int (*bind_int64)(sqlite3_stmt*, int, long long);
    int (*bind_double)(sqlite3_stmt*, int, double);
    int (*bind_null)(sqlite3_stmt*, int);
    int (*column_count)(sqlite3_stmt*);
    const char* (*column_name)(sqlite3_stmt*, int);
    int (*column_type)(sqlite3_stmt*, int);
    long long (*column_int64)(sqlite3_stmt*, int);
    double (*column_double)(sqlite3_stmt*, int);
    const unsigned char* (*column_text)(sqlite3_stmt*, int);
    const void* (*column_blob)(sqlite3_stmt*, int);
    int (*column_bytes)(sqlite3_stmt*, int);
    int (*exec)(sqlite3*, const char*, int (*)(void*, int, char**, char**), void*, char**);
    void (*free)(void*);
    const char* (*errmsg)(sqlite3*);
    int (*changes)(sqlite3*);
    long long (*last_insert_rowid)(sqlite3*);
    int (*busy_timeout)(sqlite3*, int);
    int (*get_autocommit)(sqlite3*);
    int (*initialize)();
} api;
bool loaded = false;
#define SQLITE_TRANSIENT_FN ((void (*)(void*)) - 1)
} // namespace

bool Db::load_library(std::string& error)
{
    if (loaded) return true;
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    std::wstring folder(path);
    folder = folder.substr(0, folder.find_last_of(L"\\/") + 1);
    HMODULE module = LoadLibraryW((folder + L"sqlite3.dll").c_str());
    if (!module) module = LoadLibraryW(L"sqlite3.dll");
    if (!module)
    {
        error = "sqlite3.dll is missing next to the server executable";
        return false;
    }
    bool ok = true;
    auto bind = [&](auto& target, const char* name) {
        target = reinterpret_cast<std::remove_reference_t<decltype(target)>>(GetProcAddress(module, name));
        if (!target) ok = false;
    };
    bind(api.open_v2, "sqlite3_open_v2"); bind(api.close_v2, "sqlite3_close_v2");
    bind(api.prepare_v2, "sqlite3_prepare_v2"); bind(api.finalize, "sqlite3_finalize");
    bind(api.step, "sqlite3_step"); bind(api.bind_text, "sqlite3_bind_text");
    bind(api.bind_int64, "sqlite3_bind_int64"); bind(api.bind_double, "sqlite3_bind_double");
    bind(api.bind_null, "sqlite3_bind_null"); bind(api.column_count, "sqlite3_column_count");
    bind(api.column_name, "sqlite3_column_name"); bind(api.column_type, "sqlite3_column_type");
    bind(api.column_int64, "sqlite3_column_int64"); bind(api.column_double, "sqlite3_column_double");
    bind(api.column_text, "sqlite3_column_text"); bind(api.column_bytes, "sqlite3_column_bytes");
    bind(api.exec, "sqlite3_exec"); bind(api.free, "sqlite3_free"); bind(api.errmsg, "sqlite3_errmsg");
    bind(api.changes, "sqlite3_changes"); bind(api.last_insert_rowid, "sqlite3_last_insert_rowid");
    bind(api.busy_timeout, "sqlite3_busy_timeout"); bind(api.get_autocommit, "sqlite3_get_autocommit");
    bind(api.initialize, "sqlite3_initialize");
    bind(api.bind_blob,"sqlite3_bind_blob");bind(api.column_blob,"sqlite3_column_blob");
    if (!ok)
    {
        error = "sqlite3.dll is too old";
        return false;
    }
    // Python's sqlite3.dll is built with SQLITE_OMIT_AUTOINIT: open() without
    // this crashes on its uninitialised mutex methods (CI 2026-10-19).
    if (api.initialize() != SQLITE_OK)
    {
        error = "sqlite3_initialize failed";
        return false;
    }
    loaded = true;
    return true;
}

Db::~Db() { close(); }

void Db::open(const std::wstring& path, bool read_only)
{
    std::string error;
    if (!load_library(error)) throw Unavailable(error);
    sqlite3* db = nullptr;
    int flags = (read_only ? OPEN_READONLY : OPEN_READWRITE | OPEN_CREATE) | OPEN_FULLMUTEX;
    if (api.open_v2(narrow(path).c_str(), &db, flags, nullptr) != SQLITE_OK)
    {
        if (db) api.close_v2(db);
        throw Unavailable("world database cannot be opened");
    }
    api.busy_timeout(db, 5000);
    handle_ = db;
}

void Db::close()
{
    if (handle_)
    {
        api.close_v2((sqlite3*)handle_);
        handle_ = nullptr;
    }
}

void Db::run(const std::string& sql, const Params& params, const std::function<bool(void*)>& row)
{
    if (!handle_) throw Unavailable("store is closed");
    sqlite3_stmt* stmt = nullptr;
    if (api.prepare_v2((sqlite3*)handle_, sql.c_str(), int(sql.size()), &stmt, nullptr) != SQLITE_OK)
        throw Unavailable(std::string("SQL error: ") + api.errmsg((sqlite3*)handle_));
    struct Finalize { sqlite3_stmt* s; ~Finalize() { api.finalize(s); } } finalize{ stmt };
    for (size_t i = 0; i < params.size(); ++i)
    {
        const json& p = params[i];
        int index = int(i + 1);
        if (p.is_null()) api.bind_null(stmt, index);
        else if (p.is_boolean()) api.bind_int64(stmt, index, p.get<bool>() ? 1 : 0);
        else if (p.is_number_integer()) api.bind_int64(stmt, index, p.is_number_unsigned() ? (long long)p.get<uint64_t>() : p.get<int64_t>());
        else if (p.is_number_float()) api.bind_double(stmt, index, p.get<double>());
        else if (p.is_string())
        {
            const std::string& s = p.get_ref<const std::string&>();
            api.bind_text(stmt, index, s.data(), int(s.size()), SQLITE_TRANSIENT_FN);
        }
        else if(p.is_binary()) {const auto& bytes=p.get_binary();api.bind_blob(stmt,index,bytes.data(),int(bytes.size()),SQLITE_TRANSIENT_FN);}
        else throw Invalid("unsupported SQL parameter");
    }
    while (true)
    {
        int rc = api.step(stmt);
        if (rc == SQLITE_ROW)
        {
            if (!row(stmt)) break;
            continue;
        }
        if (rc == SQLITE_DONE) break;
        std::string message = api.errmsg((sqlite3*)handle_);
        if (message.find("constraint") != std::string::npos || message.find("UNIQUE") != std::string::npos)
            throw Unavailable("integrity: " + message);  // sqlite3.IntegrityError -> 503 in Python
        throw Unavailable("SQL error: " + message);
    }
}

static json read_row(void* handle)
{
    auto stmt = (sqlite3_stmt*)handle;
    json row = json::object();
    int count = api.column_count(stmt);
    for (int c = 0; c < count; ++c)
    {
        const char* name = api.column_name(stmt, c);
        switch (api.column_type(stmt, c))
        {
        case SQLITE_INTEGER: row[name] = int64_t(api.column_int64(stmt, c)); break;
        case SQLITE_FLOAT: row[name] = api.column_double(stmt, c); break;
        case SQLITE_NULL: row[name] = nullptr; break;
        case SQLITE_BLOB: {
            const auto* data=static_cast<const uint8_t*>(api.column_blob(stmt,c));
            const int size=api.column_bytes(stmt,c);
            row[name]=json::binary(size ? std::vector<uint8_t>(data,data+size):std::vector<uint8_t>());break;
        }
        default:
        {
            const unsigned char* text = api.column_text(stmt, c);
            row[name] = std::string((const char*)text, size_t(api.column_bytes(stmt, c)));
        }
        }
    }
    return row;
}

json Db::one(const std::string& sql, const Params& params)
{
    json result;
    run(sql, params, [&](void* stmt) { result = read_row(stmt); return false; });
    return result;
}

std::vector<json> Db::all(const std::string& sql, const Params& params)
{
    std::vector<json> rows;
    run(sql, params, [&](void* stmt) { rows.push_back(read_row(stmt)); return true; });
    return rows;
}

json Db::scalar(const std::string& sql, const Params& params)
{
    json value;
    run(sql, params, [&](void* stmt) {
        json row = read_row(stmt);
        auto s = (sqlite3_stmt*)stmt;
        value = row[api.column_name(s, 0)];
        return false;
    });
    return value;
}

int64_t Db::exec(const std::string& sql, const Params& params)
{
    run(sql, params, [](void*) { return true; });
    return api.changes((sqlite3*)handle_);
}

int64_t Db::last_rowid() { return api.last_insert_rowid((sqlite3*)handle_); }

void Db::script(const std::string& sql)
{
    if (!handle_) throw Unavailable("store is closed");
    char* message = nullptr;
    if (api.exec((sqlite3*)handle_, sql.c_str(), nullptr, nullptr, &message) != SQLITE_OK)
    {
        std::string text = message ? message : "SQL script failed";
        if (message) api.free(message);
        throw Unavailable("SQL error: " + text);
    }
}

bool Db::in_transaction() { return handle_ && api.get_autocommit((sqlite3*)handle_) == 0; }
} // namespace lzm

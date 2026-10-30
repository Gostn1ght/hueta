// console.py: the operator's commands, typed in the master window.
#include "lzm_service.h"

#include <map>
#include <sstream>

namespace lzm
{
static const char* HELP =
    "Команды: status, clock, locations, players, characters, npcs, transfers, events, "
    "scale <число>, weather, emission, psi, help.\n"
    "weather <исходный цикл> <новый цикл> <секунды перехода>;\n"
    "emission|psi <секунды предупреждения> <до пика> <после пика> <интенсивность>.\n"
    "Длительности: 0.001..86400 игровых секунд; интенсивность: (0,100].\n"
    "Мастер задаёт календарь, погоду, выбросы и пси-штормы подключённых карт.";

static double py_float(const std::string& text)
{
    // float(): decimal text with optional sign/exponent, inf/nan refused later by finite().
    std::string t = trim(text);
    size_t used = 0;
    double v = std::stod(t, &used);  // std::invalid_argument -> ValueError
    if (used != t.size()) throw std::invalid_argument("could not convert string to float");
    return v;
}

static std::string number_text(const json& value)
{
    return value.is_number_float() ? python_float(value.get<double>()) : value.dump();
}

std::string Service::timeline_command(const std::string& name, const std::vector<std::string>& args)
{
    if (args.empty())
    {
        std::lock_guard<std::recursive_mutex> guard(store_->lock);
        store_->require_epoch(store_->db);
        json row = store_->db.one("SELECT state FROM world_state WHERE name=?", { name });
        if (row.is_null()) return name + ": расписание ещё не задано.";
        const std::string& text = row["state"].get_ref<const std::string&>();
        if (text.size() > 65536) throw Invalid("timeline exceeds console read limit");
        json state = Timelines::evaluate(name, loads(text), world_->now());
        const json& p = state["parameters"];
        std::string details = name == "weather"
                                  ? p["source"].get<std::string>() + " -> " + p["target"].get<std::string>() + "; blend=" + format("%.3f", state["blend"].get<double>())
                                  : "intensity=" + number_text(p["intensity"]);
        std::string prefix = ready_ ? "" : "Восстановление; ";
        return prefix + name + ": " + state["phase"].get<std::string>() + "; " + details + ".";
    }
    if (args.size() != (name == "weather" ? 3u : 4u)) throw Invalid("invalid timeline command arguments");
    json parameters, durations = json::array();
    if (name == "weather")
    {
        parameters = { { "source", args[0] }, { "target", args[1] } };
        durations.push_back(py_float(args[2]));
    }
    else
    {
        parameters = { { "intensity", py_float(args[3]) } };
        for (int i = 0; i < 3; ++i) durations.push_back(py_float(args[size_t(i)]));
    }
    std::string command_id = uuid4_hex();
    auto [times, planned] = Timelines::plan(*world_, name, command_id, durations, parameters);
    parameters = planned;
    if (!ready_) throw Unavailable("world recovery has not completed");
    Principal admin;
    for (auto& entry : credentials_->entries)
        if (entry.second.role == "admin") { admin = entry.second; break; }
    json result = execute(admin, { { "command_id", command_id }, { "operation", "timeline_schedule" },
                                   { "arguments", { { "name", name }, { "timeline_id", command_id }, { "version", nullptr },
                                                    { "times", times }, { "parameters", parameters } } } });
    return name + ": расписание сохранено; version=" + result["version"].dump() + "; ID=" + result["timeline_id"].get<std::string>() + ".";
}

std::string Service::console(const std::string& line)
{
    try
    {
        if (line.size() > 256) throw Invalid("console command too long");
        std::istringstream in(line);
        std::vector<std::string> parts;
        for (std::string word; in >> word;) parts.push_back(word);
        if (parts.empty()) return "";
        std::string command = lower(parts[0]);
        std::vector<std::string> args(parts.begin() + 1, parts.end());
        if (command == "weather" || command == "emission") return timeline_command(command, args);
        if (command == "psi") return timeline_command("psi_storm", args);
        if (command == "scale")
        {
            if (args.size() != 1) throw Invalid("scale requires one number");
            if (!ready_) throw Unavailable("world recovery has not completed");
            Principal admin;
            for (auto& entry : credentials_->entries)
                if (entry.second.role == "admin") { admin = entry.second; break; }
            json result = execute(admin, { { "command_id", uuid4_hex() }, { "operation", "world_scale" }, { "arguments", { { "value", py_float(args[0]) } } } });
            return "Масштаб времени: " + number_text(result["scale"]) + "; календарь: " + number_text(result["world_ms"]) + " мс.";
        }
        if(command=="role") {
            if(args.size()!=2 || (args[1]!="admin" && args[1]!="player")) throw Invalid("role <login> admin|player");
            const auto login=lower(args[0]);
            const auto changed=store_->transaction([&](Db& tx)->json {
                store_->require_epoch(tx);
                const auto revision=tx.scalar("SELECT COALESCE(MAX(revision),0)+1 FROM account");
                return tx.exec("UPDATE account SET role=?,revision=? WHERE key=?",{args[1],revision,login});
            });
            log_line(format("[diag][accounts] operator role=%s matched=%s",args[1].c_str(),changed.dump().c_str()));
            return changed==0 ? "Аккаунт не найден.":"Роль сохранена. Подключённые карты применят её без перезахода.";
        }
        if (!args.empty()) throw Invalid("command does not take arguments");
        if (command == "help") return HELP;
        if (command == "quit" || command == "exit") return "Мастер останавливается кнопкой «Остановить».";
        std::lock_guard<std::recursive_mutex> guard(store_->lock);
        auto rows = [&](const char* sql) {
            store_->require_epoch(store_->db);
            return store_->db.all(sql);
        };
        if(command=="accounts") {
            std::string text;
            for(const auto& row:rows("SELECT login,role,approval FROM account ORDER BY key LIMIT 513"))
                text+=row["login"].get<std::string>()+" | "+row["role"].get<std::string>()+" | "+row["approval"].get<std::string>()+"\n";
            return text.empty() ? "Аккаунтов пока нет.":text;
        }
        if (command == "status")
        {
            json status = recovery_status();
            const json& world = status["world"];
            return format("Мастер: %s; WorldID=%s; epoch=%lld.\n", status["admission_ready"].get<bool>() ? "готов" : "восстанавливается",
                          world["world_id"].get<std::string>().c_str(), (long long)world["epoch"].get<int64_t>()) +
                   "Просроченные события (выборка): " + status["due_sample_count"].dump() + "; обработано: " + status["events_processed"].dump() +
                   "; ошибка worker: " + (status["worker_error_type"].is_null() ? std::string("нет") : status["worker_error_type"].get<std::string>()) + ".";
        }
        if (command == "clock")
        {
            json scale = rows("SELECT scale FROM world WHERE singleton=1")[0]["scale"];
            return "Календарь: " + python_float(world_->now()) + " мс; масштаб времени: " + number_text(scale) + ".";
        }
        if (command == "locations")
        {
            auto list = rows("SELECT location,owner,fence,expires_ms FROM location_lease ORDER BY location LIMIT 65");
            std::string text;
            for (size_t i = 0; i < list.size() && i < 64; ++i)
                text += (i ? "\n" : "") + list[i]["location"].get<std::string>() + ": владелец=" + list[i]["owner"].get<std::string>() +
                        "; fence=" + list[i]["fence"].dump() + "; expires=" + list[i]["expires_ms"].dump();
            if (list.size() > 64) text += "\nПоказаны первые 64 локации.";
            return text.empty() ? "Локации ещё не подключились к мастеру." : text;
        }
        if (command == "players")
        {
            auto list = rows("SELECT s.account AS account, s.state AS state, e.location AS location "
                             "FROM player_session s JOIN entity e ON e.id=s.character_id "
                             "WHERE s.state IN ('ACTIVE','FROZEN') ORDER BY e.location, s.account LIMIT 513");
            std::string text;
            for (size_t i = 0; i < list.size() && i < 512; ++i)
                text += (i ? "\n" : "") + list[i]["location"].get<std::string>() + ": " + list[i]["account"].get<std::string>() +
                        (list[i]["state"] == "FROZEN" ? " (в переходе)" : "");
            return text.empty() ? "Сейчас в мире никого нет." : text;
        }
        if (command == "characters")
        {
            auto characters = rows("SELECT id FROM character ORDER BY id LIMIT 1025");
            auto sessions = rows("SELECT state FROM player_session ORDER BY character_id LIMIT 1025");
            std::map<std::string, int> counts;
            for (size_t i = 0; i < sessions.size() && i < 1024; ++i) counts[sessions[i]["state"].get<std::string>()]++;
            std::string listed;
            for (auto& c : counts) listed += (listed.empty() ? "" : ", ") + c.first + "=" + std::to_string(c.second);
            return "Персонажей: " + std::to_string(std::min<size_t>(characters.size(), 1024)) + (characters.size() > 1024 ? "+" : "") +
                   ". Сессии (выборка до 1024): " + (listed.empty() ? "нет" : listed) + (sessions.size() > 1024 ? "; есть ещё записи" : "");
        }
        if (command == "npcs")
        {
            auto list = rows("SELECT kind,alive FROM entity ORDER BY id LIMIT 1025");
            std::map<std::pair<std::string, int64_t>, int> counts;
            for (size_t i = 0; i < list.size() && i < 1024; ++i)
            {
                std::string kind = list[i]["kind"].get<std::string>();
                if (kind == "NPC" || kind == "MUTANT" || kind == "GROUP") counts[{ kind, list[i]["alive"].get<int64_t>() }]++;
            }
            std::string text;
            for (auto& c : counts)
                text += (text.empty() ? "" : "\n") + c.first.first + ": alive=" + std::to_string(c.first.second) + "; записей=" + std::to_string(c.second);
            return "Первые 1024 записи реестра:\n" + (text.empty() ? std::string("В этой выборке NPC нет.") : text) +
                   (list.size() > 1024 ? "\nЕсть ещё записи реестра." : "");
        }
        if (command == "transfers")
        {
            auto list = rows("SELECT state FROM transfer ORDER BY id LIMIT 1025");
            std::map<std::string, int> counts;
            for (size_t i = 0; i < list.size() && i < 1024; ++i) counts[list[i]["state"].get<std::string>()]++;
            std::string listed;
            for (auto& c : counts) listed += (listed.empty() ? "" : ", ") + c.first + "=" + std::to_string(c.second);
            return "Переходы (выборка до 1024): " + (listed.empty() ? "нет" : listed) + (list.size() > 1024 ? "; есть ещё записи" : "");
        }
        if (command == "events")
        {
            auto list = rows("SELECT sequence,type,aggregate_id,world_ms FROM world_event ORDER BY sequence DESC LIMIT 10");
            std::string text;
            for (auto& row : list)
                text += (text.empty() ? "" : "\n") + std::string("#") + row["sequence"].dump() + " " + row["type"].get<std::string>() + " " +
                        row["aggregate_id"].get<std::string>() + " @ " + number_text(row["world_ms"]) + " мс";
            return text.empty() ? "Глобальных событий пока нет." : text;
        }
        throw Invalid("unknown console command");
    }
    catch (const std::exception& error)
    {
        // Configs, arguments and exception text can contain secrets: the class only.
        return "Команда не выполнена (" + exception_type(error) + "). help — список команд.";
    }
}
} // namespace lzm

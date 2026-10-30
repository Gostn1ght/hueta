#pragma once
#include "lzm_common.h"

namespace lzm
{
void create_config(const std::wstring& path, std::vector<std::string> locations, std::optional<uint64_t> world_id,
                   std::optional<uint64_t> seed, std::optional<double> initial_ms, std::optional<double> scale);
bool add_location_credential(const std::wstring& path, const std::string& location);
void create_writer_config(const std::wstring& config, const std::wstring& destination, const std::string& location, bool replace);
void create_bridge_config(const std::wstring& config, const std::wstring& destination, bool authority, bool replace);
// Idempotent native bootstrap: complete the plan, preserve/import the old DB,
// and issue every map's current credentials without external processes.
void prepare_engine_cluster(const std::wstring& root, const std::wstring& config, const std::wstring& plan);
// The engine entry: `-netcoop_master <mode> --config ...` (modes of __main__.py
// plus `window`, the master with its own window). Returns the exit code.
int master_main(const std::vector<std::wstring>& args);
} // namespace lzm

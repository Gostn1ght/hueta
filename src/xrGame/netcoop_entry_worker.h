#pragma once
#include <cstddef>

namespace netcoop_world
{
// Single UI-owner caller; background thread owns all JSON/HTTP and never engine state.
// Fixed bounded output across the exception-disabled engine boundary.
void poll_entry_route(const char* address,const char* account,int slot,char* answer,std::size_t capacity) noexcept;
void stop_entry_route() noexcept;
}

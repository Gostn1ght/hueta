#pragma once
#include <algorithm>
#include <set>
#include <vector>
#include <utility>

namespace netcoop
{
// Packed recursion originates only inside a root destroy that passed ownership
// checks. The server's local client is also trusted to clean up migrated items.
inline bool destroy_authorized(bool packed, bool server, bool owned)
{
    return packed || server || owned;
}

template<class Read, class Linked>
bool destroy_tree_valid(unsigned root, Read read, Linked linked)
{
    std::vector<std::pair<unsigned, unsigned>> pending{{root, 0}};
    std::set<unsigned> seen;
    while (!pending.empty())
    {
        const auto node = pending.back(); pending.pop_back();
        if (node.second > 32 || seen.size() >= 4096 || !seen.insert(node.first).second) return false;
        const auto* children = read(node.first);
        if (!children || children->size() > 4096) return false;
        for (const auto child : *children)
        {
            if (!linked(node.first, child)) return false;
            pending.emplace_back(child, node.second + 1);
        }
    }
    return true;
}

template<class Children, class Destroy>
bool destroy_children(Children& children, Destroy destroy)
{
    while (!children.empty())
    {
        const auto id = children.front();
        const auto before = children.size();
        destroy(id);
        // A refused child used to spin here forever, blocking all locations'
        // players and printing tens of millions of identical rejections.
        if (children.size() >= before || std::find(children.begin(), children.end(), id) != children.end()) return false;
    }
    return true;
}
}

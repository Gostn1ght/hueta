#pragma once
#include <vector>

// Reserve separate positions before changing inventory ownership. This also
// covers a whole stack dropped in one frame, before the spatial index updates.
class NetcoopDropLayout
{
    struct Spot { Fvector position; float radius; };
    std::vector<Spot> spots_;
    u32 last_ = 0;
public:
    template<class Free>
    bool reserve(u32 now, float radius, const Fvector& origin, const Fvector& forward, Fvector& result, Free free)
    {
        if (now - last_ > 500) spots_.clear();
        last_ = now;
        if (!_valid(radius)) return false;
        radius = _max(.08f, _min(.7f, radius));
        if (spots_.size() >= 128) return false;
        for (int row = 0; row < 16; ++row)
            for (int column = 0; column < 13; ++column)
            {
                const int side = (column % 2 ? -1 : 1) * ((column + 1) / 2);
                const float across = float(side) * .24f;
                const float ahead = .75f + float(row) * .24f;
                Fvector point = origin;
                point.x += forward.x * ahead + forward.z * across;
                point.z += forward.z * ahead - forward.x * across;
                bool separate = true;
                for (const Spot& spot : spots_)
                    if (point.distance_to(spot.position) < radius + spot.radius + .04f) { separate = false; break; }
                if (!separate || !free(point, radius)) continue;
                result = point;
                spots_.push_back({point, radius});
                return true;
            }
        return false;
    }
};

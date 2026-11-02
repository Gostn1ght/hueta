"""Player movement speed on the server (CActor::netcoop_follow_owner): besides
the owner-time step limit (12 m/s, +1 m), a distance budget on the server's
clock (12 m/s, at most 13 m saved up) bounds the accepted horizontal steps.
A model of the same arithmetic: forged time stamps 1 s apart at 30 Hz (was
~390 m/s) stay at the 12 m/s average; honest running at 30 Hz and updates
that arrive bunched after a 0.5 s lag keep their full steps."""
from pathlib import Path
import re

src = (Path(__file__).resolve().parents[1] / "src/xrGame/Actor_Network.cpp").read_text(encoding="utf-8", errors="replace")
body = src[src.index("void CActor::netcoop_follow_owner"):]
refill = "m_netcoop_move_budget = _min(m_netcoop_noclip ? 65.f:13.f, m_netcoop_move_budget + (m_netcoop_noclip ? 64.f:12.f) * float(now - m_netcoop_move_budget_time) / 1000.f);"
limit = "const float allowed_h = _min((m_netcoop_noclip ? 64.f:12.f) * dt + 1.f, m_netcoop_move_budget);"
spend = "m_netcoop_move_budget = _max(0.f, m_netcoop_move_budget - _sqrt(delta.x * delta.x + delta.z * delta.z));"
assert body.index(refill) < body.index(limit) < body.index(spend)
header = (Path(__file__).resolve().parents[1] / "src/xrGame/Actor.h").read_text(encoding="utf-8", errors="replace")
assert re.search(r"float m_netcoop_move_budget = 13\.f;", header)


def run(updates):
    """updates: (server ms, owner ms, claimed metres along a line); returns accepted metres."""
    pos, owner_time, budget, budget_time = 0.0, 0, 13.0, 0
    for server_ms, owner_ms, claimed in updates:
        dt = 0.1
        if owner_time and owner_ms > owner_time:
            dt = (owner_ms - owner_time) / 1000.0
        dt = min(max(dt, 0.02), 1.0)
        if budget_time:
            budget = min(13.0, budget + 12.0 * (server_ms - budget_time) / 1000.0)
        budget_time = server_ms
        if not owner_time or owner_ms > owner_time:
            owner_time = owner_ms
        allowed = min(12.0 * dt + 1.0, budget)
        step = min(claimed - pos, allowed)
        pos += step
        budget = max(0.0, budget - step)
    return pos

# forged: owner clock jumps 1 s per packet, sent every 33 ms for 3 s, claims 13 m each
moved = run([(33 * n, 1000 * n, 13.0 * n) for n in range(1, 91)])
assert moved <= 13.0 + 12.0 * 33 * 89 / 1000.0 + 1e-6, moved
# honest: 6 m/s at 30 Hz for 3 s
assert abs(run([(33 * n, 33 * n, 0.198 * n) for n in range(1, 91)]) - 0.198 * 90) < 1e-6
# lag: nothing for 0.5 s, then the delayed updates within 15 ms
burst = [(33 * n, 33 * n, 0.198 * n) for n in range(1, 31)]
burst += [(990 + 500 + k, 33 * (30 + k), 0.198 * (30 + k)) for k in range(1, 16)]
assert abs(run(burst) - 0.198 * 45) < 1e-6
# sprint at 9 m/s for 10 s is never cut
assert abs(run([(33 * n, 33 * n, 0.297 * n) for n in range(1, 301)]) - 0.297 * 300) < 1e-6
print("Player movement: 12 m/s distance budget on the server's clock, honest steps kept: PASS")

# Remaining independent particle CPU work and empty Follow safety

User priority21November: stop graph design, keep one personal all-time checkbox file and finish multithreading first. Obsidian keeps canonical engineering evidence; personal checkboxes are not rewritten and are not automatic game acceptance.

The independent particle actions now also include Avoid, Bounce and Follow. Domain geometry and neighbour positions are frozen until the synchronous fence; only each particle's own velocity changes. The outer action sequence, RNG-dependent generators, birth/death callbacks and storage mutation remain on their original owner. Follow reads the next particle's immutable position, not its velocity.

A concrete existing bug is fixed: Follow loop bounds used unsigned particle_count-1. With count0 that becomes UINT_MAX and the loop accesses invalid particles. The new path returns for count<2. No claim is made that this explains a particular reported game crash without a matching dump.

Pairwise gravitation calculates forces in bounded65536-pair batches (<=1.5MiB scratch) using immutable positions, then applies them on the owner in the original i/j and +=/-= order. Each force is calculated once; no quadratic temporary array or duplicate force calculations. Single/two-slot hosts, small inputs, serial flags or allocation failure retain the original direct pair loop. Output calculations may safely replay after scheduler failure; mutable application happens once after the fence. Velocity matching remains serial because it reads earlier velocity updates. No arbitrary Lua/ALife flags are enabled.

CI fixture now compiles20 actual actions, the actual pDomain constructor/Within code, actual pVector operators/Particle fields and actual noise. Core vector/color/effect boundaries remain doubles; a full DX11/DX8 build is required for engine ABI. The fixture covers all relevant geometry domains, finite/unbounded lookahead and force radius, friction cutoffs, immutable neighbour boundaries, zero-count Follow safety, chunk/threshold boundaries, canaries and partial scheduler failures. Pair gravity also crosses the65536-record buffer boundary. Timings are synthetic, not gameFPS.

Native/game/fixtures remain GitHub Actions only; local Python/static/packaging is allowed. At this commit native/fixture results are pending, installed83 remains unchanged and game acceptance remains open.

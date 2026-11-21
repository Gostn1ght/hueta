# Remaining independent particle CPU work and empty Follow safety

User priority21November: stop graph design, keep one personal all-time checkbox file and finish multithreading first. Obsidian keeps canonical engineering evidence; personal checkboxes are not rewritten and are not automatic game acceptance.

The independent particle actions now also include Avoid, Bounce and Follow. Domain geometry and neighbour positions are frozen until the synchronous fence; only each particle's own velocity changes. The outer action sequence, RNG-dependent generators, birth/death callbacks and storage mutation remain on their original owner. Follow reads the next particle's immutable position, not its velocity.

A concrete existing bug is fixed: Follow loop bounds used unsigned particle_count-1. With count0 that becomes UINT_MAX and the loop accesses invalid particles. The new path returns for count<2. No claim is made that this explains a particular reported game crash without a matching dump.

Pairwise gravitation uses per-particle local velocity accumulation: first subtract lower-index pair contributions, then add upper-index contributions, exactly matching the original accumulation order. Positions are frozen, and a worker writes only its own particle. Each pair force is evaluated twice;128-particle chunks distribute the quadratic work. Single/two-slot hosts, small inputs and serial flags retain the original loop. At-most-once scheduling prevents duplicate velocity changes after partial scheduler failure. Velocity matching remains serial because it reads earlier velocity updates. No arbitrary Lua/ALife flags are enabled.

The first buffered approach was rejected after actual CI timings: serial9981us versus parallel15665.6us at2048particles, despite correct output. The replacement removes the serial apply pass and pair staging; it must pass exact-output checks and a fresh benchmark before acceptance.

CI fixture now compiles20 actual actions, the actual pDomain constructor/Within code, actual pVector operators/Particle fields and actual noise. Core vector/color/effect boundaries remain doubles; a full DX11/DX8 build is required for engine ABI. The fixture covers all relevant geometry domains, finite/unbounded lookahead and force radius, friction cutoffs, immutable neighbour boundaries, zero-count Follow safety, chunk/threshold boundaries, canaries and partial scheduler failures. Pair gravity also crosses128-particle chunk boundaries. Timings are synthetic, not gameFPS.

Native/game/fixtures remain GitHub Actions only; local Python/static/packaging is allowed. At this commit native/fixture results are pending, installed83 remains unchanged and game acceptance remains open.

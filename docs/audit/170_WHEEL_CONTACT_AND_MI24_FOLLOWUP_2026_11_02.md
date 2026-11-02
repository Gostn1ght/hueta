# Follow-up 170 — not released
Installed public version remains 2026.11.02.6. Work continues per owner steering.

Confirmed production defect: SWheel::applywheelCollisionParams supplied
soft_cfm for both reference arguments of MulSprDmp(cfm,erp,...). Non-unit
DCP damping therefore scaled compliance twice while leaving ERP unchanged.
Fixed to distinct soft_cfm/soft_erp. CI-only native suspension fixture now
executes the actual callback and actual helper against independently derived
spring/damping equations for 9 factor combinations; no driving claim.

Network road cars still received the legacy single-player half-gravity
compensation in PhTune/EffectiveGravity. Enabled multiplayer now keeps full
world gravity, consistent with the existing mass-based suspension sag model.
Single-player legacy compensation retained; actual native fixture covers both.

Mi-24 travel and gear ground clearance now have explicit bounded model
parameters, preserving old defaults until the corrected model is ready. This
alone does not repair the visibly wrong primitive struts. Original source
gear, wheel wells and contact plane are being inspected before asset changes.

Native candidate 08c07a2ce, CI 41497354805 pending. No local native build or
owner game/master launch. Do not mark general physics or Mi-24 finished.

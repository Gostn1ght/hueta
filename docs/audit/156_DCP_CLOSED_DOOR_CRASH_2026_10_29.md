# 156. DCP spawn crash, 2026-10-29

Continue engine-restructure after 6516182cf. No game or local native compiler
was started. This change is additional to document 155, not a replacement.

## Reproduced from the owner's dump

The October 26 22:59:33 client dump matches native 25afdf144. The matching
PDB was downloaded to J:/LostZone_Work/_work/symbols_25afdf144. Its original
PE CodeView alias is LostZoneDX11.pdb. Manual x64 unwind using the exception
context and the PE unwind metadata gives:

- CPHElement::GetGlobalTransformDynamic, PHElement.cpp:747, reads null body + D8.
- CPHShell::GetGlobalTransformDynamic, PHShell.cpp:1274.
- CPHSkeleton::Spawn, PHSkeleton.cpp:111.
- CCar::net_Spawn, Car.cpp:234.
- CLevel::g_sv_Spawn / cl_Process_Spawn / ProcessSpawnEvents.

Earlier raw stack scanning also found SDoor::Init and get_Extensions. Those
are stale stack values, **not** frames in the unwound exception. The actual
failure occurs *after* initialization closes the doors. ClosingToClosed
deactivates/destroys the door body while leaving the element in the shell;
the shell's whole-object query then dereferences every body unconditionally.

## Changes

- Whole-shell dynamic and interpolated transform queries skip inactive parts.
  The root remains authoritative; inactive doors keep their skeleton pose.
- Inactive parts export complete disabled physics state from the current
  skeleton/world pose and local mass center, with zero velocities/forces.
  Applying a packet to an inactive part returns before touching interpolation.
- Fix() preserves the fixed flag without calling ODE on a missing body.
- Shell destruction skips already inactive parts/joints; repeated door closing
  is harmless. Clear queued door pointers before their owning map.
- Car restore checks both saved part counts before applying indexed state;
  changed models use default part state rather than reading past a vector or
  applying part of an incompatible layout. Invalid door enum falls back closed.
- Missing door map lookup cannot dereference end().
- The expanded driving-profile audit found DT-75 has no steering-wheel joint.
  Its ordinary physics tick dereferenced the empty list. Guard that query and
  test the actual expression with empty and ordinary lists. This prevents the
  additional crash; DT-75's absent differential-steering implementation is not
  solved by pretending it has an automobile's steerable axle.

## Validation / delivery

- Expanded check-netcoop-dcp.py parses actual OGF bone names, hierarchy and IK
  records, validates positive collision sizes and masses, wheel joints, single
  door hinge axes and all profile bone references. All 50 cars pass locally.
- Existing vehicle/trunk/transition and helicopter checks pass locally.
- New check-native-car-lifecycle.py compiles actual shell query, physics state,
  Fix and restore bodies on CI. Tests closed-door spawn, interpolation, packet
  export/import, reopening, missing body Fix and changed save layouts.
- Run 40839684203 timed out in checkout before running any checks. The checks
  job's previous 10-minute limit is now 30 minutes for this asset-heavy repo.
- Native compilation, complete workflow result and publication remain pending.
  Do not call this runtime-tested or claim all possible vehicle crashes fixed.

#ifndef _ODE_PARALLEL_STEP_H_
#define _ODE_PARALLEL_STEP_H_
#include "common.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Scoped per-thread suppression of dxStepBody's shared-space notifications.
 * The owner MUST refresh every stepped world's geoms after joining its jobs. */
int dThreadSetGeomNotificationsDeferred(int deferred);
void dWorldRefreshGeoms(dWorldID world);
/* Same QuickStep solver and shuffle algorithm, with an isolated RNG stream.
 * Results do not depend on which worker happens to execute this world. */
void dWorldQuickStepSeeded(dWorldID world,dReal stepsize,unsigned int seed);
#ifdef __cplusplus
}
#endif
#endif

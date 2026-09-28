/* firmware/main/relays.h -- GPIO coil drive for the 4 contactor channels via the
 * ULN2003 Darlington array (03-Parts-Placement-and-Roles.md C7).
 *
 * Semantics (CONTRACTS.md §5, autopilot.h AP_CH_SHED): coil energised = SHED on the
 * NC (normally-closed) contactors, i.e. energising the coil OPENS the sub-circuit
 * and turns the load OFF. All coils de-energised (= all loads ON) is therefore the
 * safe/fail state, so this module de-energises everything at boot and on any
 * detected fault, before anything else runs (design 04 §6 "Brown-out/crash/hang:
 * any reset drops coils -> loads on").
 *
 * ESP-IDF specific (driver/gpio.h), NEVER BUILT here.
 */
#ifndef SENTINEL_RELAYS_H
#define SENTINEL_RELAYS_H

#include <stdbool.h>

#include "autopilot.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int gpio[AP_N_CHANNELS];   /* SENTINEL_RELAY_COIL_{T1,T2,T3,MED}_GPIO from Kconfig */
    int heartbeat_gpio;
    bool task_watchdog_healthy; /* set by the caller each tick; heartbeat only
                                    toggles while this is true (design 04 §2) */
} relays_t;

/* Configures the 4 coil GPIOs + heartbeat GPIO as outputs and immediately
 * de-energises every coil (fail-safe default: all loads ON). Returns 0 on
 * success, negative on a GPIO config failure. */
int relays_init(relays_t *r, const int coil_gpio[AP_N_CHANNELS], int heartbeat_gpio);

/* Applies channel_state[] (from ap_output_t, CONTRACTS §5) to the coil GPIOs.
 * AP_CH_SHED -> coil energised (load off); AP_CH_ON -> coil de-energised (load
 * on). Explicit error handling: if any gpio_set_level call fails, this function
 * immediately de-energises ALL coils (not just the one that failed) and returns
 * negative -- a half-applied relay state is never left standing. */
int relays_apply(relays_t *r, const ap_chstate_t channel_state[AP_N_CHANNELS]);

/* Immediately de-energises every coil (all loads on). Call on any detected
 * fault (task watchdog trip, sensor fault escalation, etc) -- this is the
 * function main.c's fault paths call, not relays_apply(). */
int relays_all_safe(relays_t *r);

/* Toggles the heartbeat GPIO iff r->task_watchdog_healthy is true -- call once
 * per heartbeat task tick (design 04 §2, prio 24, "toggles ... only if all
 * critical tasks checked in"). The external supervisory timer (03 §1 C8) drops
 * all coils itself if this stops toggling, independent of this firmware. */
void relays_heartbeat_tick(relays_t *r);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_RELAYS_H */

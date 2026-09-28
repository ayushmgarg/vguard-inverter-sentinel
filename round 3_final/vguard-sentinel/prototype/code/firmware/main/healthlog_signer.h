/* firmware/main/healthlog_signer.h -- target-specific hl_sign_cb backend.
 *
 * healthlog.h's contract: "This library never holds or touches a private key --
 * hl_append hashes the record and calls a caller-supplied hl_sign_cb, which on
 * this host prototype wraps an OpenSSL software key ... and on the target MCU
 * would talk to the ATECC608 over I2C." This header is that target-side half.
 *
 * ESP32 target: healthlog_signer_esp_init()/_sign_cb() (healthlog_signer_esp.c).
 * Host: firmware/host/sentinel_host_sim.c defines its own OpenSSL-backed signer
 * directly (mirrors healthlog/test_healthlog_host.c, which already does exactly
 * this and is the pattern to follow) -- not declared here since it depends on
 * openssl/*.h, which the ESP32 component build must never pull in.
 */
#ifndef SENTINEL_HEALTHLOG_SIGNER_H
#define SENTINEL_HEALTHLOG_SIGNER_H

#include "healthlog.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Returns 0 on success (a real ATECC608 driver would probe the part over I2C
 * here). This prototype has no ATECC608 driver -- see healthlog_signer_esp.c --
 * so this always fails until one is written; the return code lets main.c decide
 * whether to boot in "health log disabled, everything else runs" mode rather
 * than silently pretending events are being signed. */
int healthlog_signer_esp_init(void *i2c_bus_handle, uint8_t i2c_addr);

/* hl_sign_cb-compatible entry point. Documented stub: returns nonzero
 * (HL_ERR_SIGN_FAILED-triggering) until a real ATECC608 driver exists. */
int healthlog_signer_esp_sign_cb(const uint8_t hash32[HL_HASH_SIZE], uint8_t sig64[HL_SIG_SIZE], void *ctx);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_HEALTHLOG_SIGNER_H */

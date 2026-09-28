/* firmware/main/healthlog_signer_esp.c -- see healthlog_signer.h.
 *
 * HONEST LIMIT (see firmware/README.md): there is no ATECC608 driver in this
 * prototype -- no hardware was available, and writing a correct ATECC608
 * command-set driver (I2C wake pulse, CRC-16 framing, ECDSA-Sign command,
 * polling for the busy->ready transition) is out of scope for this firmware-
 * glue pass. This file is therefore a deliberate, clearly-marked stub: it
 * compiles and links (satisfying the healthlog component's hl_sign_cb contract)
 * but never actually signs anything. main.c must treat a nonzero
 * healthlog_signer_esp_init() return as "health log disabled this boot" --
 * design 04 §6's "sensor fault" philosophy applied to the health log: don't
 * pretend, degrade visibly.
 */
#include "healthlog_signer.h"

#include <stdbool.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_log.h"
static const char *TAG = "healthlog_signer_esp";
#endif

static bool s_probed = false;

int healthlog_signer_esp_init(void *i2c_bus_handle, uint8_t i2c_addr) {
    (void)i2c_bus_handle; (void)i2c_addr;
#ifdef ESP_PLATFORM
    ESP_LOGW(TAG, "no ATECC608 driver in this prototype -- health-log signing disabled");
#endif
    s_probed = false;
    return -1;
}

int healthlog_signer_esp_sign_cb(const uint8_t hash32[HL_HASH_SIZE], uint8_t sig64[HL_SIG_SIZE], void *ctx) {
    (void)hash32; (void)ctx;
    memset(sig64, 0, HL_SIG_SIZE);
    if (!s_probed) return 1; /* hl_append maps any nonzero return to HL_ERR_SIGN_FAILED */
    return 1; /* unreachable until a real driver replaces this stub */
}

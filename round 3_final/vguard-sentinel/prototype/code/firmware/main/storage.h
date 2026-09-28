/* firmware/main/storage.h -- NVS commissioning config + LittleFS append log.
 *
 * NVS ("nvs" partition, 64 KB, partitions.csv): battery Ah, shunt mOhm, CT ratio,
 * circuit map/tiers, hw-lock, EKF persisted state, model pointer -- design 04 §3/§6
 * ("Commissioning (USB or BLE, 10 min): battery model/Ah, shunt value, CT ratio and
 * polarity check, circuit map + tiers, region, tariff, consent").
 *
 * LittleFS ("data" partition, 1 MB): feature history (36 B/cycle), NILM events
 * (64 B), PQ events (32 B), telemetry queue, health-log chain.
 *
 * ESP-IDF specific (nvs_flash.h, esp_littlefs.h), NEVER BUILT here.
 */
#ifndef SENTINEL_STORAGE_H
#define SENTINEL_STORAGE_H

#include <stdbool.h>
#include <stdint.h>

#include "autopilot.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float    q_rated_ah;
    float    shunt_mohm;
    float    ct_ratio;
    ap_tier_t channel_tier[AP_N_CHANNELS];
    bool      channel_hw_locked[AP_N_CHANNELS];
    bool      configured;         /* false = first boot / unconfigured, design 04 §6 */
    uint32_t crc32;                /* covers every field above except itself, computed
                                       by storage_config_save() and checked by
                                       storage_config_load() -- a corrupt/partial NVS
                                       blob must never be silently trusted */
} sentinel_commission_config_t;

/* Initialises the NVS flash partition (calls nvs_flash_init(), erasing and
 * retrying once on NVS_ERR_NOT_FOUND/NEW_VERSION_FOUND per the standard
 * ESP-IDF pattern) and mounts LittleFS on the "data" partition. Returns 0 on
 * success. */
int storage_init(void);

/* Loads the commissioning config from NVS. On any failure (not yet
 * commissioned, or a CRC mismatch on a corrupt blob) fills *out with the
 * design 04 §6 fail-safe default: every channel forced T1 (hw_locked=false but
 * tier=AP_TIER_T1, so the app itself never sheds anything until explicitly
 * commissioned), configured=false. Returns 0 if a valid config was loaded, 1 if
 * the fail-safe default was used instead (not an error -- expected on first
 * boot), negative on an NVS access error. */
int storage_config_load(sentinel_commission_config_t *out);

/* Writes cfg to NVS (with a fresh CRC32) and commits. Returns 0 on success. */
int storage_config_save(const sentinel_commission_config_t *cfg);

/* Appends `len` bytes of `data` to a named LittleFS log file under /data/logs/
 * (e.g. "features.bin", "healthlog.bin", "nilm_events.bin", "pq_events.bin").
 * Returns 0 on success, negative on a filesystem error -- callers must not
 * assume the append succeeded without checking (coding-style: explicit error
 * handling on every driver call). */
int storage_append(const char *log_name, const uint8_t *data, uint32_t len);

/* Reads the full current contents of a LittleFS log file into buf (caller-sized,
 * e.g. for hl_resume_verified() at boot to pick the health log back up).
 * Returns the number of bytes read (>=0), or negative on error/buffer-too-small. */
int32_t storage_read_all(const char *log_name, uint8_t *buf, uint32_t buf_cap);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_STORAGE_H */

/* firmware/main/storage.c -- see storage.h. ESP-IDF specific, NEVER BUILT here. */
#include "storage.h"

#include <string.h>
#include <stdio.h>

#ifdef ESP_PLATFORM
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_littlefs.h"
#include "esp_log.h"
static const char *TAG = "storage";
#endif

#define NVS_NAMESPACE "sentinel"
#define NVS_KEY_CONFIG "commission"
#define LITTLEFS_MOUNT "/data"
#define LITTLEFS_PARTITION_LABEL "data"

/* Small self-contained CRC32 (poly 0xEDB88320, reflected) -- no dependency on a
 * particular crypto library, matches the algorithm every common CRC32 table uses. */
static uint32_t crc32_update(uint32_t crc, const uint8_t *buf, uint32_t len) {
    crc = ~crc;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 1u) crc = (crc >> 1) ^ 0xEDB88320u;
            else crc >>= 1;
        }
    }
    return ~crc;
}

int storage_init(void) {
#ifdef ESP_PLATFORM
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "nvs_flash_init needs erase (%d), retrying once", err);
        if (nvs_flash_erase() != ESP_OK) return -1;
        err = nvs_flash_init();
    }
    if (err != ESP_OK) { ESP_LOGE(TAG, "nvs_flash_init failed: %d", err); return -1; }

    esp_vfs_littlefs_conf_t conf = {
        .base_path = LITTLEFS_MOUNT,
        .partition_label = LITTLEFS_PARTITION_LABEL,
        .format_if_mount_failed = true,
        .dont_mount = false,
    };
    err = esp_vfs_littlefs_register(&conf);
    if (err != ESP_OK) { ESP_LOGE(TAG, "littlefs mount failed: %d", err); return -2; }
    return 0;
#else
    return -1; /* host build uses plain files, see host/sentinel_host_sim.c */
#endif
}

int storage_config_load(sentinel_commission_config_t *out) {
    if (!out) return -1;
    sentinel_commission_config_t fail_safe;
    memset(&fail_safe, 0, sizeof(fail_safe));
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        fail_safe.channel_tier[i] = AP_TIER_T1;   /* design 04 §6: unconfigured -> never shed */
        fail_safe.channel_hw_locked[i] = false;
    }
    fail_safe.configured = false;

#ifdef ESP_PLATFORM
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) { *out = fail_safe; return 1; }

    sentinel_commission_config_t tmp;
    size_t sz = sizeof(tmp);
    err = nvs_get_blob(h, NVS_KEY_CONFIG, &tmp, &sz);
    nvs_close(h);
    if (err != ESP_OK || sz != sizeof(tmp)) { *out = fail_safe; return 1; }

    uint32_t stored_crc = tmp.crc32;
    tmp.crc32 = 0;
    uint32_t computed = crc32_update(0, (const uint8_t *)&tmp, sizeof(tmp));
    if (computed != stored_crc) {
        ESP_LOGE(TAG, "commission config CRC mismatch -- falling back to fail-safe default");
        *out = fail_safe;
        return 1;
    }
    tmp.crc32 = stored_crc;
    *out = tmp;
    return 0;
#else
    *out = fail_safe;
    return 1;
#endif
}

int storage_config_save(const sentinel_commission_config_t *cfg) {
    if (!cfg) return -1;
    sentinel_commission_config_t tmp = *cfg;
    tmp.crc32 = 0;
    tmp.crc32 = crc32_update(0, (const uint8_t *)&tmp, sizeof(tmp));

#ifdef ESP_PLATFORM
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) return -2;
    esp_err_t err = nvs_set_blob(h, NVS_KEY_CONFIG, &tmp, sizeof(tmp));
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return (err == ESP_OK) ? 0 : -3;
#else
    (void)tmp;
    return -2;
#endif
}

int storage_append(const char *log_name, const uint8_t *data, uint32_t len) {
    if (!log_name || !data) return -1;
#ifdef ESP_PLATFORM
    char path[128];
    snprintf(path, sizeof(path), "%s/logs/%s", LITTLEFS_MOUNT, log_name);
    FILE *f = fopen(path, "ab");
    if (!f) { ESP_LOGE(TAG, "storage_append: cannot open %s", path); return -2; }
    size_t written = fwrite(data, 1, len, f);
    int close_rc = fclose(f);
    if (written != len || close_rc != 0) return -3;
    return 0;
#else
    (void)len;
    return -2;
#endif
}

int32_t storage_read_all(const char *log_name, uint8_t *buf, uint32_t buf_cap) {
    if (!log_name || !buf) return -1;
#ifdef ESP_PLATFORM
    char path[128];
    snprintf(path, sizeof(path), "%s/logs/%s", LITTLEFS_MOUNT, log_name);
    FILE *f = fopen(path, "rb");
    if (!f) return 0; /* no prior log is not an error -- fresh device */
    size_t n = fread(buf, 1, buf_cap, f);
    bool truncated = (fgetc(f) != EOF);
    fclose(f);
    if (truncated) { ESP_LOGE(TAG, "storage_read_all: %s exceeds buf_cap=%u", path, (unsigned)buf_cap); return -2; }
    return (int32_t)n;
#else
    (void)buf_cap;
    return -2;
#endif
}

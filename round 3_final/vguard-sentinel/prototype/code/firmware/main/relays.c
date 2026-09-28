/* firmware/main/relays.c -- see relays.h. ESP-IDF specific, NEVER BUILT here. */
#include "relays.h"

#include <string.h>

#ifdef ESP_PLATFORM
#include "driver/gpio.h"
#include "esp_log.h"
static const char *TAG = "relays";
#endif

static int gpio_out(int gpio) {
#ifdef ESP_PLATFORM
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << gpio,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE, /* fail-safe: floating input before
                                                  this runs must not float the
                                                  ULN2003 base into "energised" */
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&cfg) != ESP_OK) { ESP_LOGE(TAG, "gpio_config(%d) failed", gpio); return -1; }
    return 0;
#else
    (void)gpio;
    return -1;
#endif
}

static int gpio_set(int gpio, int level) {
#ifdef ESP_PLATFORM
    if (gpio_set_level((gpio_num_t)gpio, level) != ESP_OK) {
        ESP_LOGE(TAG, "gpio_set_level(%d,%d) failed", gpio, level);
        return -1;
    }
    return 0;
#else
    (void)gpio; (void)level;
    return -1;
#endif
}

int relays_init(relays_t *r, const int coil_gpio[AP_N_CHANNELS], int heartbeat_gpio) {
    if (!r || !coil_gpio) return -1;
    memset(r, 0, sizeof(*r));
    for (int i = 0; i < AP_N_CHANNELS; i++) r->gpio[i] = coil_gpio[i];
    r->heartbeat_gpio = heartbeat_gpio;
    r->task_watchdog_healthy = false;

    int rc = 0;
    for (int i = 0; i < AP_N_CHANNELS; i++) rc |= gpio_out(r->gpio[i]);
    rc |= gpio_out(r->heartbeat_gpio);
    if (rc != 0) return -2;

    return relays_all_safe(r);
}

int relays_apply(relays_t *r, const ap_chstate_t channel_state[AP_N_CHANNELS]) {
    if (!r || !channel_state) return -1;
    for (int i = 0; i < AP_N_CHANNELS; i++) {
        int level = (channel_state[i] == AP_CH_SHED) ? 1 : 0;
        if (gpio_set(r->gpio[i], level) != 0) {
            /* explicit error handling: never leave a half-applied relay state */
            relays_all_safe(r);
            return -2;
        }
    }
    return 0;
}

int relays_all_safe(relays_t *r) {
    if (!r) return -1;
    int rc = 0;
    for (int i = 0; i < AP_N_CHANNELS; i++) rc |= gpio_set(r->gpio[i], 0);
    return rc;
}

void relays_heartbeat_tick(relays_t *r) {
    if (!r || !r->task_watchdog_healthy) return;
#ifdef ESP_PLATFORM
    static int level = 0;
    level = !level;
    gpio_set(r->heartbeat_gpio, level);
#endif
}

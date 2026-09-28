/* firmware/main/ntc.c -- see ntc.h. ESP-IDF specific, NEVER BUILT here. */
#include "ntc.h"

#include <math.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
static const char *TAG = "ntc";
#endif

#define NTC_MIN_VALID_C -40.0f
#define NTC_MAX_VALID_C 85.0f
#define ADC_MAX_RAW 4095.0f   /* 12-bit ADC, ESP32-S3 default width */

int ntc_init(ntc_t *dev, void *adc_handle, int adc_channel,
             float r_fixed_ohm, float r0_ohm, float t0_c, float beta, float vcc_v, bool ntc_on_top) {
    if (!dev || r_fixed_ohm <= 0.0f || r0_ohm <= 0.0f || beta <= 0.0f || vcc_v <= 0.0f) return -1;
    memset(dev, 0, sizeof(*dev));
    dev->adc_handle = adc_handle;
    dev->adc_channel = adc_channel;
    dev->r_fixed_ohm = r_fixed_ohm;
    dev->r0_ohm = r0_ohm;
    dev->t0_c = t0_c;
    dev->beta = beta;
    dev->vcc_v = vcc_v;
    dev->ntc_on_top = ntc_on_top;
    return 0;
}

int ntc_read_celsius(ntc_t *dev, float *out_c) {
    if (!dev || !out_c) return -1;

    int raw = 0;
#ifdef ESP_PLATFORM
    esp_err_t err = adc_oneshot_read((adc_oneshot_unit_handle_t)dev->adc_handle,
                                      (adc_channel_t)dev->adc_channel, &raw);
    if (err != ESP_OK) { ESP_LOGE(TAG, "adc_oneshot_read failed: %d", err); return -2; }
#else
    (void)raw;
    return -2; /* host build never calls this */
#endif

    float v_node = (raw / ADC_MAX_RAW) * dev->vcc_v;
    if (v_node <= 0.0f || v_node >= dev->vcc_v) return -3; /* open/short */

    float r_ntc;
    if (dev->ntc_on_top) {
        /* Vcc -[NTC]- node -[Rfixed]- GND: v_node = Vcc * Rfixed/(Rntc+Rfixed) */
        r_ntc = dev->r_fixed_ohm * (dev->vcc_v - v_node) / v_node;
    } else {
        /* Vcc -[Rfixed]- node -[NTC]- GND: v_node = Vcc * Rntc/(Rntc+Rfixed) */
        r_ntc = dev->r_fixed_ohm * v_node / (dev->vcc_v - v_node);
    }
    if (r_ntc <= 0.0f) return -3;

    float t0_k = dev->t0_c + 273.15f;
    float inv_t = 1.0f / t0_k + (1.0f / dev->beta) * logf(r_ntc / dev->r0_ohm);
    float t_c = (1.0f / inv_t) - 273.15f;

    if (t_c < NTC_MIN_VALID_C || t_c > NTC_MAX_VALID_C || isnan(t_c)) return -4;

    *out_c = t_c;
    return 0;
}

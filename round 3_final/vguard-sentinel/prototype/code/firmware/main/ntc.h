/* firmware/main/ntc.h -- ADC + beta-equation NTC thermistor driver.
 * 03-Parts-Placement-and-Roles.md C4: NTC 10k beta3950, divider to an ESP32-S3 ADC
 * pin. ESP-IDF specific (driver/adc_oneshot.h), NEVER BUILT here.
 */
#ifndef SENTINEL_NTC_H
#define SENTINEL_NTC_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    void   *adc_handle;      /* adc_oneshot_unit_handle_t, opaque */
    int     adc_channel;      /* adc_channel_t */
    float   r_fixed_ohm;      /* divider's fixed resistor, e.g. 10000 */
    float   r0_ohm;            /* NTC nominal resistance at t0_c, e.g. 10000 */
    float   t0_c;               /* nominal temp, 25.0 */
    float   beta;               /* beta3950 -> 3950.0 */
    float   vcc_v;               /* divider supply, 3.3 */
    bool    ntc_on_top;           /* true: Vcc-NTC-node-Rfixed-GND (node rises with T);
                                     false: Vcc-Rfixed-node-NTC-GND */
} ntc_t;

int  ntc_init(ntc_t *dev, void *adc_handle, int adc_channel,
              float r_fixed_ohm, float r0_ohm, float t0_c, float beta, float vcc_v, bool ntc_on_top);

/* Reads the ADC, converts to resistance via the divider equation, then to
 * temperature via the beta equation: 1/T = 1/T0 + (1/beta)*ln(R/R0).
 * Returns 0 on success and sets *out_c; negative on ADC failure or an
 * out-of-range reading (open/shorted sensor -- design 04 §6 "sensor fault"). */
int ntc_read_celsius(ntc_t *dev, float *out_c);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_NTC_H */

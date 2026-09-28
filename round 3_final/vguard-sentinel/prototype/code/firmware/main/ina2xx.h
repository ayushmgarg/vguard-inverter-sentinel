/* firmware/main/ina2xx.h -- I2C driver for TI INA226 (16-bit) and INA228 (20-bit
 * delta-sigma) current/voltage monitors, 03-Parts-Placement-and-Roles.md C3.
 *
 * ESP-IDF specific (uses driver/i2c_master.h, ESP-IDF 5.x's new I2C master API).
 * NEVER BUILT in this environment (no ESP-IDF here) -- register addresses/bit
 * layouts below are transcribed from the public TI datasheets (SBOS717 for
 * INA226, SBOS929 for INA228) but have not been bench-verified against real
 * silicon; see firmware/README.md "honest limits".
 */
#ifndef SENTINEL_INA2XX_H
#define SENTINEL_INA2XX_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum { INA_KIND_INA226 = 0, INA_KIND_INA228 = 1 } ina_kind_t;

typedef struct {
    void   *i2c_bus_handle;   /* i2c_master_bus_handle_t, opaque here to keep this
                                  header includable from portable/host code paths
                                  that never dereference it */
    uint8_t i2c_addr;          /* 7-bit address, default 0x40 (both parts) */
    ina_kind_t kind;
    float   shunt_ohm;         /* 03 §2 X1: 0.1 or 0.15 mOhm depending on shunt SKU */
    float   max_expected_a;    /* for CAL register scaling, design margin above
                                  the battery's rated discharge current */
    float   i_offset_a;        /* zero-current auto-cal offset, updated at runtime */
} ina2xx_t;

typedef struct {
    float voltage_v;   /* bus voltage */
    float current_a;   /* +discharge convention chosen at the driver boundary --
                           see ina2xx.c doc comment; main.c flips to CONTRACTS §1's
                           +charge/-discharge before publishing a Sample */
    float power_w;
    bool  valid;         /* false on any I2C error -- caller must not trust the
                            other fields when false (explicit error handling rule) */
} ina2xx_reading_t;

/* Returns 0 on success, negative esp_err_t-style code on failure (I2C probe/config
 * failed). Programs the CAL register for `shunt_ohm`/`max_expected_a` (design 01
 * needs current resolution << the C20 tail-current threshold). */
int ina2xx_init(ina2xx_t *dev, void *i2c_bus_handle, uint8_t i2c_addr, ina_kind_t kind,
                 float shunt_ohm, float max_expected_a);

/* One-shot read of V/I/P. Returns 0 on success; on I2C failure returns a negative
 * code and sets out->valid = false (caller falls back per design 04 §6 "sensor
 * fault" behaviour -- EKF drops to coulomb-count-only, never shed on unreliable
 * data). */
int ina2xx_read(ina2xx_t *dev, ina2xx_reading_t *out);

/* Zero-current auto-cal (design 01 §4): call periodically while the caller has
 * independently determined the pack is at rest (|I| below noise floor, charger
 * off) -- updates dev->i_offset_a with an EWMA, matching ekf.h's own
 * zero_cal_alpha/zero_cal_i_thresh_a semantics on the *measurement* side (the EKF
 * does its own separate internal offset estimate on the value this driver hands
 * it; the two are complementary, not redundant -- driver-side cal corrects a
 * slowly-drifting ADC/shunt offset, the EKF's is a fast per-boot settle). */
void ina2xx_update_zero_cal(ina2xx_t *dev, float measured_i_a, float rest_i_thresh_a, float alpha);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_INA2XX_H */

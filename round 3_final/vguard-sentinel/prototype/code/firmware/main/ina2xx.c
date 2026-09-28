/* firmware/main/ina2xx.c -- see ina2xx.h. ESP-IDF specific, NEVER BUILT here.
 *
 * Sign convention: this driver reports current in whatever polarity the shunt
 * wiring gives it (X1's Kelvin taps, 03-Parts-Placement-and-Roles.md §2) -- it
 * does not itself decide charge/discharge sign. main.c's sense_1hz task is the
 * one place that maps the raw driver reading onto CONTRACTS.md §1's
 * +charge/-discharge convention, after the commissioning-time polarity check
 * (design 04 §6 "sign of P" check) has established which way is which on this
 * install.
 */
#include "ina2xx.h"

#include <math.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "driver/i2c_master.h"
#include "esp_log.h"
static const char *TAG = "ina2xx";
#endif

/* ---- INA226 register map (TI SBOS717) ---- */
#define INA226_REG_CONFIG        0x00
#define INA226_REG_SHUNT_V       0x01   /* 16-bit signed, 2.5 uV/LSB */
#define INA226_REG_BUS_V         0x02   /* 16-bit unsigned, 1.25 mV/LSB */
#define INA226_REG_POWER         0x03
#define INA226_REG_CURRENT       0x04
#define INA226_REG_CALIBRATION   0x05
#define INA226_CONFIG_RESET      0x8000
#define INA226_CONFIG_DEFAULT    0x4527 /* avg=1, 1.1ms conv, cont shunt+bus */

/* ---- INA228 register map (TI SBOS929, 20-bit delta-sigma) ---- */
#define INA228_REG_CONFIG        0x00
#define INA228_REG_ADC_CONFIG    0x01
#define INA228_REG_SHUNT_CAL     0x02
#define INA228_REG_VSHUNT        0x04   /* 24-bit signed, top 20 bits used, 312.5 nV/LSB @ ADCRANGE=0 */
#define INA228_REG_VBUS          0x05   /* 24-bit signed, top 20 bits used, 195.3125 uV/LSB */
#define INA228_REG_CURRENT       0x07   /* 24-bit signed, scaled by SHUNT_CAL/CURRENT_LSB */
#define INA228_REG_POWER         0x08   /* 24-bit unsigned */
#define INA228_CONFIG_RESET      0x8000
#define INA228_ADC_CONFIG_DEFAULT 0xFB68 /* continuous bus+shunt+temp, 1052us conv, avg=4 */

static int i2c_write_reg16(ina2xx_t *dev, uint8_t reg, uint16_t val) {
#ifdef ESP_PLATFORM
    uint8_t buf[3] = { reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFF) };
    esp_err_t err = i2c_master_transmit((i2c_master_dev_handle_t)dev->i2c_bus_handle, buf, sizeof(buf), 100);
    if (err != ESP_OK) { ESP_LOGE(TAG, "write reg 0x%02x failed: %d", reg, err); return -1; }
    return 0;
#else
    (void)dev; (void)reg; (void)val;
    return -1; /* host build never calls this -- see firmware/host/README notes */
#endif
}

static int i2c_read_regN(ina2xx_t *dev, uint8_t reg, uint8_t *out, size_t n) {
#ifdef ESP_PLATFORM
    esp_err_t err = i2c_master_transmit_receive((i2c_master_dev_handle_t)dev->i2c_bus_handle,
                                                 &reg, 1, out, n, 100);
    if (err != ESP_OK) { ESP_LOGE(TAG, "read reg 0x%02x failed: %d", reg, err); return -1; }
    return 0;
#else
    (void)dev; (void)reg; (void)out; (void)n;
    return -1;
#endif
}

int ina2xx_init(ina2xx_t *dev, void *i2c_bus_handle, uint8_t i2c_addr, ina_kind_t kind,
                 float shunt_ohm, float max_expected_a) {
    if (!dev || shunt_ohm <= 0.0f || max_expected_a <= 0.0f) return -1;
    memset(dev, 0, sizeof(*dev));
    dev->i2c_bus_handle = i2c_bus_handle;
    dev->i2c_addr = i2c_addr;
    dev->kind = kind;
    dev->shunt_ohm = shunt_ohm;
    dev->max_expected_a = max_expected_a;
    dev->i_offset_a = 0.0f;

    if (kind == INA_KIND_INA226) {
        if (i2c_write_reg16(dev, INA226_REG_CONFIG, INA226_CONFIG_RESET) != 0) return -2;
        if (i2c_write_reg16(dev, INA226_REG_CONFIG, INA226_CONFIG_DEFAULT) != 0) return -2;
        /* CAL = 0.00512 / (current_lsb * Rshunt); current_lsb chosen so max_expected_a
         * uses close to the full 15-bit signed range (design 01 §4 wants current
         * resolution well below the C20 tail-current threshold). */
        float current_lsb = max_expected_a / 32768.0f;
        uint16_t cal = (uint16_t)(0.00512f / (current_lsb * shunt_ohm));
        if (i2c_write_reg16(dev, INA226_REG_CALIBRATION, cal) != 0) return -2;
    } else {
        if (i2c_write_reg16(dev, INA228_REG_CONFIG, INA228_CONFIG_RESET) != 0) return -2;
        if (i2c_write_reg16(dev, INA228_REG_ADC_CONFIG, INA228_ADC_CONFIG_DEFAULT) != 0) return -2;
        float current_lsb = max_expected_a / 524288.0f; /* 2^19, 20-bit signed */
        uint16_t shunt_cal = (uint16_t)(13107.2e6f * current_lsb * shunt_ohm);
        if (i2c_write_reg16(dev, INA228_REG_SHUNT_CAL, shunt_cal) != 0) return -2;
    }
    return 0;
}

int ina2xx_read(ina2xx_t *dev, ina2xx_reading_t *out) {
    if (!dev || !out) return -1;
    out->valid = false;

    if (dev->kind == INA_KIND_INA226) {
        uint8_t buf[2];
        if (i2c_read_regN(dev, INA226_REG_BUS_V, buf, 2) != 0) return -2;
        uint16_t bus_raw = ((uint16_t)buf[0] << 8) | buf[1];
        float v = bus_raw * 1.25e-3f;

        if (i2c_read_regN(dev, INA226_REG_CURRENT, buf, 2) != 0) return -2;
        int16_t i_raw = (int16_t)(((uint16_t)buf[0] << 8) | buf[1]);
        float current_lsb = dev->max_expected_a / 32768.0f;
        float i = i_raw * current_lsb - dev->i_offset_a;

        out->voltage_v = v;
        out->current_a = i;
        out->power_w = v * i;
        out->valid = true;
        return 0;
    } else {
        uint8_t buf[3];
        if (i2c_read_regN(dev, INA228_REG_VBUS, buf, 3) != 0) return -2;
        int32_t vbus_raw = ((int32_t)buf[0] << 16) | ((int32_t)buf[1] << 8) | buf[2];
        vbus_raw >>= 4; /* 24-bit register, low 4 bits reserved -> 20-bit value */
        float v = vbus_raw * 195.3125e-6f;

        if (i2c_read_regN(dev, INA228_REG_CURRENT, buf, 3) != 0) return -2;
        int32_t i_raw = ((int32_t)buf[0] << 16) | ((int32_t)buf[1] << 8) | buf[2];
        i_raw >>= 4;
        if (i_raw & 0x80000) i_raw |= ~0xFFFFF; /* sign-extend 20-bit */
        float current_lsb = dev->max_expected_a / 524288.0f;
        float i = i_raw * current_lsb - dev->i_offset_a;

        out->voltage_v = v;
        out->current_a = i;
        out->power_w = v * i;
        out->valid = true;
        return 0;
    }
}

void ina2xx_update_zero_cal(ina2xx_t *dev, float measured_i_a, float rest_i_thresh_a, float alpha) {
    if (!dev) return;
    if (fabsf(measured_i_a) < rest_i_thresh_a) {
        dev->i_offset_a = alpha * measured_i_a + (1.0f - alpha) * dev->i_offset_a;
    }
}

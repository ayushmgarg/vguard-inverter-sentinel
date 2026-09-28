/* nilm/pzem_parser.c -- see pzem_parser.h */
#include "pzem_parser.h"

uint16_t pzem_crc16(const uint8_t *buf, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)buf[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 0x0001) {
                crc = (crc >> 1) ^ 0xA001;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}

static uint16_t be16(const uint8_t *p) {
    return (uint16_t)((p[0] << 8) | p[1]);
}

int pzem_parse_frame(const uint8_t *buf, size_t len, pzem_reading_t *out) {
    if (len != PZEM_FRAME_LEN) return -1;
    if (buf[1] != PZEM_FUNC_READ) return -2;
    if (buf[2] != 20) return -3;

    uint16_t crc_calc = pzem_crc16(buf, len - 2);
    uint16_t crc_frame = (uint16_t)(buf[len - 2] | (buf[len - 1] << 8)); /* lo byte first */
    if (crc_calc != crc_frame) return -4;

    const uint8_t *d = buf + 3; /* start of the 20-byte register payload */
    uint16_t reg_v      = be16(d + 0);
    uint16_t reg_i_lo   = be16(d + 2);
    uint16_t reg_i_hi   = be16(d + 4);
    uint16_t reg_p_lo   = be16(d + 6);
    uint16_t reg_p_hi   = be16(d + 8);
    uint16_t reg_e_lo   = be16(d + 10);
    uint16_t reg_e_hi   = be16(d + 12);
    uint16_t reg_f      = be16(d + 14);
    uint16_t reg_pf     = be16(d + 16);
    uint16_t reg_alarm  = be16(d + 18);

    uint32_t i_raw = ((uint32_t)reg_i_hi << 16) | reg_i_lo;
    uint32_t p_raw = ((uint32_t)reg_p_hi << 16) | reg_p_lo;
    uint32_t e_raw = ((uint32_t)reg_e_hi << 16) | reg_e_lo;

    out->slave_addr    = buf[0];
    out->voltage_v     = reg_v * 0.1f;
    out->current_a     = i_raw * 0.001f;
    out->power_w       = p_raw * 0.1f;
    out->energy_wh     = (float)e_raw;
    out->frequency_hz  = reg_f * 0.1f;
    out->power_factor  = reg_pf * 0.01f;
    out->alarm         = (reg_alarm == 0xFFFF) ? 1 : 0;
    return 0;
}

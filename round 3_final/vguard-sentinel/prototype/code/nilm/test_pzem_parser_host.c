/* nilm/test_pzem_parser_host.c -- host unit test for the PZEM-004T v3 frame
 * parser: builds a canned frame with a known CRC, checks decoding, then
 * corrupts the CRC and checks rejection. Build & run via `make test`.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "pzem_parser.h"

static int g_failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { fprintf(stderr, "FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); g_failures++; } \
} while (0)

static void put_be16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v & 0xFF);
}

int main(void) {
    uint8_t frame[PZEM_FRAME_LEN];
    frame[0] = 0x01;             /* slave addr */
    frame[1] = PZEM_FUNC_READ;   /* 0x04 */
    frame[2] = 20;               /* byte count */

    uint8_t *d = frame + 3;
    put_be16(d + 0, 2300);         /* 230.0 V */
    put_be16(d + 2, 12345);        /* current low: 12.345 A LSB part */
    put_be16(d + 4, 0);            /* current high */
    put_be16(d + 6, 15000);        /* power low: 1500.0 W (0.1W LSB) */
    put_be16(d + 8, 0);            /* power high */
    put_be16(d + 10, 4660);        /* energy low */
    put_be16(d + 12, 1);           /* energy high -> 65536+4660 = 70196 Wh */
    put_be16(d + 14, 500);         /* 50.0 Hz */
    put_be16(d + 16, 95);          /* PF 0.95 */
    put_be16(d + 18, 0x0000);      /* no alarm */

    uint16_t crc = pzem_crc16(frame, PZEM_FRAME_LEN - 2);
    frame[PZEM_FRAME_LEN - 2] = (uint8_t)(crc & 0xFF);       /* lo byte first */
    frame[PZEM_FRAME_LEN - 1] = (uint8_t)((crc >> 8) & 0xFF);

    pzem_reading_t r;
    int rc = pzem_parse_frame(frame, PZEM_FRAME_LEN, &r);
    CHECK(rc == 0, "valid frame should parse successfully");
    if (rc == 0) {
        CHECK(r.slave_addr == 0x01, "slave address");
        CHECK(fabsf(r.voltage_v - 230.0f) < 1e-3f, "voltage decode");
        CHECK(fabsf(r.current_a - 12.345f) < 1e-3f, "current decode");
        CHECK(fabsf(r.power_w - 1500.0f) < 1e-3f, "power decode");
        CHECK(fabsf(r.energy_wh - 70196.0f) < 1e-3f, "energy (32-bit) decode");
        CHECK(fabsf(r.frequency_hz - 50.0f) < 1e-3f, "frequency decode");
        CHECK(fabsf(r.power_factor - 0.95f) < 1e-3f, "power factor decode");
        CHECK(r.alarm == 0, "no alarm");
    }

    /* corrupt CRC -> must be rejected */
    uint8_t bad[PZEM_FRAME_LEN];
    memcpy(bad, frame, PZEM_FRAME_LEN);
    bad[PZEM_FRAME_LEN - 1] ^= 0xFF;
    pzem_reading_t r2;
    int rc2 = pzem_parse_frame(bad, PZEM_FRAME_LEN, &r2);
    CHECK(rc2 == -4, "corrupted CRC must be rejected with -4");

    /* alarm register set */
    uint8_t alarmed[PZEM_FRAME_LEN];
    memcpy(alarmed, frame, PZEM_FRAME_LEN);
    put_be16(alarmed + 3 + 18, 0xFFFF);
    uint16_t crc3 = pzem_crc16(alarmed, PZEM_FRAME_LEN - 2);
    alarmed[PZEM_FRAME_LEN - 2] = (uint8_t)(crc3 & 0xFF);
    alarmed[PZEM_FRAME_LEN - 1] = (uint8_t)((crc3 >> 8) & 0xFF);
    pzem_reading_t r3;
    int rc3 = pzem_parse_frame(alarmed, PZEM_FRAME_LEN, &r3);
    CHECK(rc3 == 0 && r3.alarm == 1, "alarm register 0xFFFF decodes to alarm=1");

    if (g_failures == 0) {
        printf("OK: all pzem_parser host tests passed\n");
        return 0;
    }
    printf("FAILED: %d check(s)\n", g_failures);
    return 1;
}

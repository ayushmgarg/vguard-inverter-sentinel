/* nilm/pzem_parser.h -- PZEM-004T v3 Modbus-RTU frame parser.
 *
 * Parses the response to "read input registers 0x0000-0x0009":
 *   [addr][func=0x04][bytecount=20][V(1 reg)][I(2 reg)][P(2 reg)]
 *   [E(2 reg)][f(1 reg)][PF(1 reg)][alarm(1 reg)][crc_lo][crc_hi]
 * Register layout and scale factors per the PZEM-004T v3 datasheet
 * (see nilm/README.md "Verify before quoting").
 */
#ifndef NILM_PZEM_PARSER_H
#define NILM_PZEM_PARSER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PZEM_FRAME_LEN 25   /* 1+1+1+20+2 */
#define PZEM_FUNC_READ 0x04

typedef struct {
    uint8_t slave_addr;
    float   voltage_v;      /* 0.1 V LSB */
    float   current_a;      /* 0.001 A LSB */
    float   power_w;        /* 0.1 W LSB */
    float   energy_wh;      /* 1 Wh LSB */
    float   frequency_hz;   /* 0.1 Hz LSB */
    float   power_factor;   /* 0.01 LSB */
    int     alarm;          /* 0 = no alarm, 1 = alarm (0xFFFF) */
} pzem_reading_t;

/* CRC-16/Modbus: init 0xFFFF, poly 0xA001 (reflected 0x8005), no xorout. */
uint16_t pzem_crc16(const uint8_t *buf, size_t len);

/* Returns 0 on success. Negative error codes:
 *  -1  frame too short / wrong length
 *  -2  unexpected function code
 *  -3  unexpected byte count
 *  -4  CRC mismatch
 */
int pzem_parse_frame(const uint8_t *buf, size_t len, pzem_reading_t *out);

#ifdef __cplusplus
}
#endif
#endif

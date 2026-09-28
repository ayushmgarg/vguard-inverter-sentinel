/* frames.h -- C99 port of documentation/prototype/code/charger/frames.py.
 *
 * UART frame codec for the Sentinel-Core <-> charger-MCU link, design doc
 * 03-Adaptive-Charging-and-Charger-Interface.md Sec.1.2:
 *
 *     [SOF 0xAA][CMD][LEN][PAYLOAD...][CRC16_L][CRC16_H][EOF 0x55]
 *
 * Must produce byte-identical frames to frames.py for the same command --
 * see tests/test_charger.py's C/Python parity test (subprocess to
 * test_frames_host, skipped if gcc is unavailable) and frames.py's module
 * docstring for the interpretive decisions (byte order, voltage units,
 * stuffing algorithm, CRC variant) shared by both ports.
 *
 * Static allocation only: no malloc/free anywhere in this module.
 */
#ifndef CHARGER_FRAMES_H
#define CHARGER_FRAMES_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FR_SOF 0xAA
#define FR_EOF 0x55
#define FR_ESC 0x7D
#define FR_ESC_XOR 0x20

#define FR_CMD_SET_FLOAT 0x10
#define FR_CMD_SET_ABSORPTION 0x11
#define FR_CMD_SET_EQUALISE 0x12
#define FR_CMD_SET_CURRENT_LIMIT_PCT 0x13
#define FR_CMD_SET_TEMP_COMP 0x14
#define FR_CMD_GET_STATUS 0x20
#define FR_CMD_HEARTBEAT 0x30
#define FR_CMD_NACK 0x7F

#define FR_STATUS_MODE_OFF 0
#define FR_STATUS_MODE_BULK 1
#define FR_STATUS_MODE_ABSORPTION 2
#define FR_STATUS_MODE_FLOAT 3
#define FR_STATUS_MODE_EQUALISE 4

#define FR_FAULT_FLAG_SENSOR 0x01
#define FR_FAULT_FLAG_HEARTBEAT_LOST 0x02

#define FR_NACK_CRC_ERROR 0
#define FR_NACK_RANGE_ERROR 1
#define FR_NACK_UNKNOWN_CMD 2
#define FR_NACK_BUSY 3

#define FR_MAX_PAYLOAD_LEN 255
/* SOF + up to 2x-stuffed(2+255+2) + EOF, rounded up generously. */
#define FR_MAX_FRAME_LEN 522
#define FR_MAX_STUFFED_BODY_LEN (4 * (2 + FR_MAX_PAYLOAD_LEN + 2))

typedef struct {
    uint8_t cmd;
    uint8_t payload[FR_MAX_PAYLOAD_LEN];
    uint16_t payload_len;
} fr_frame_t;

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflect, no xorout. */
uint16_t fr_crc16_ccitt(const uint8_t *data, size_t len, uint16_t crc);

/* Byte stuffing. out must have room for >= 2*len bytes; returns bytes written,
 * or -1 if out_cap is too small. */
int fr_stuff(const uint8_t *data, size_t len, uint8_t *out, size_t out_cap);
/* returns bytes written, or -1 on truncated escape / out_cap too small. */
int fr_unstuff(const uint8_t *data, size_t len, uint8_t *out, size_t out_cap);

/* Encode a full frame (SOF..EOF) into out. Returns bytes written, or -1 on
 * error (cmd/payload out of range, or out_cap too small). */
int fr_encode_frame(uint8_t cmd, const uint8_t *payload, size_t payload_len,
                     uint8_t *out, size_t out_cap);

int fr_encode_set_float(uint16_t mv_per_cell, uint8_t *out, size_t out_cap);
int fr_encode_set_absorption(uint16_t mv_per_cell, uint16_t timeout_min, uint8_t *out, size_t out_cap);
int fr_encode_set_equalise(uint16_t mv_per_cell, uint16_t duration_min, bool enable, uint8_t *out, size_t out_cap);
int fr_encode_set_current_limit_pct(uint8_t pct, uint8_t *out, size_t out_cap);
int fr_encode_set_temp_comp(int16_t uv_per_c_per_cell, uint8_t *out, size_t out_cap);
int fr_encode_get_status(uint8_t *out, size_t out_cap);
int fr_encode_heartbeat(uint32_t seq, uint8_t *out, size_t out_cap);
int fr_encode_nack(uint8_t code, uint8_t *out, size_t out_cap);
int fr_encode_status(uint8_t mode, uint8_t fault_flags, float v_batt_v, float i_batt_a,
                      float t_batt_c, uint8_t *out, size_t out_cap);

/* Streaming, byte-at-a-time parser state. Static allocation. */
typedef struct {
    uint8_t buf[FR_MAX_STUFFED_BODY_LEN];
    uint16_t buf_len;
    bool in_frame;
} fr_parser_t;

void fr_parser_init(fr_parser_t *p);

/* Feed one byte. Returns 1 if a valid frame completed (written to *out),
 * 0 otherwise (still mid-frame, resynchronising, or the just-completed
 * frame was malformed and was silently dropped -- never raises/aborts on
 * bad wire data). */
int fr_parser_feed_byte(fr_parser_t *p, uint8_t byte, fr_frame_t *out);

#ifdef __cplusplus
}
#endif

#endif /* CHARGER_FRAMES_H */

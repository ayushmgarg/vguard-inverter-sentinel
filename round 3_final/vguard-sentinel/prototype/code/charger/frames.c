/* frames.c -- see frames.h. C99 port of frames.py; must byte-match it. */
#include "frames.h"

#include <string.h>

uint16_t fr_crc16_ccitt(const uint8_t *data, size_t len, uint16_t crc) {
    size_t i;
    int b;
    for (i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (b = 0; b < 8; b++) {
            if (crc & 0x8000u) {
                crc = (uint16_t)((crc << 1) ^ 0x1021u);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

int fr_stuff(const uint8_t *data, size_t len, uint8_t *out, size_t out_cap) {
    size_t i, o = 0;
    for (i = 0; i < len; i++) {
        uint8_t b = data[i];
        if (b == FR_SOF || b == FR_EOF || b == FR_ESC) {
            if (o + 2 > out_cap) return -1;
            out[o++] = FR_ESC;
            out[o++] = (uint8_t)(b ^ FR_ESC_XOR);
        } else {
            if (o + 1 > out_cap) return -1;
            out[o++] = b;
        }
    }
    return (int)o;
}

int fr_unstuff(const uint8_t *data, size_t len, uint8_t *out, size_t out_cap) {
    size_t i = 0, o = 0;
    while (i < len) {
        uint8_t b = data[i];
        if (b == FR_ESC) {
            i++;
            if (i >= len) return -1; /* truncated escape */
            if (o + 1 > out_cap) return -1;
            out[o++] = (uint8_t)(data[i] ^ FR_ESC_XOR);
        } else {
            if (o + 1 > out_cap) return -1;
            out[o++] = b;
        }
        i++;
    }
    return (int)o;
}

int fr_encode_frame(uint8_t cmd, const uint8_t *payload, size_t payload_len,
                     uint8_t *out, size_t out_cap) {
    uint8_t body[2 + FR_MAX_PAYLOAD_LEN + 2];
    uint8_t stuffed[FR_MAX_STUFFED_BODY_LEN];
    uint16_t crc;
    size_t body_len;
    int stuffed_len;

    if (payload_len > FR_MAX_PAYLOAD_LEN) return -1;

    body[0] = cmd;
    body[1] = (uint8_t)payload_len;
    if (payload_len > 0 && payload != NULL) {
        memcpy(body + 2, payload, payload_len);
    }
    body_len = 2 + payload_len;

    crc = fr_crc16_ccitt(body, body_len, 0xFFFFu);
    body[body_len] = (uint8_t)(crc & 0xFFu);
    body[body_len + 1] = (uint8_t)((crc >> 8) & 0xFFu);
    body_len += 2;

    stuffed_len = fr_stuff(body, body_len, stuffed, sizeof(stuffed));
    if (stuffed_len < 0) return -1;

    if (out_cap < (size_t)stuffed_len + 2) return -1;
    out[0] = FR_SOF;
    memcpy(out + 1, stuffed, (size_t)stuffed_len);
    out[1 + (size_t)stuffed_len] = FR_EOF;
    return (int)(2 + (size_t)stuffed_len);
}

static uint16_t le16(uint16_t v) { return v; } /* host is little-endian per project convention */

int fr_encode_set_float(uint16_t mv_per_cell, uint8_t *out, size_t out_cap) {
    uint8_t payload[2];
    uint16_t v = le16(mv_per_cell);
    payload[0] = (uint8_t)(v & 0xFF);
    payload[1] = (uint8_t)((v >> 8) & 0xFF);
    return fr_encode_frame(FR_CMD_SET_FLOAT, payload, sizeof(payload), out, out_cap);
}

int fr_encode_set_absorption(uint16_t mv_per_cell, uint16_t timeout_min, uint8_t *out, size_t out_cap) {
    uint8_t payload[4];
    payload[0] = (uint8_t)(mv_per_cell & 0xFF);
    payload[1] = (uint8_t)((mv_per_cell >> 8) & 0xFF);
    payload[2] = (uint8_t)(timeout_min & 0xFF);
    payload[3] = (uint8_t)((timeout_min >> 8) & 0xFF);
    return fr_encode_frame(FR_CMD_SET_ABSORPTION, payload, sizeof(payload), out, out_cap);
}

int fr_encode_set_equalise(uint16_t mv_per_cell, uint16_t duration_min, bool enable, uint8_t *out, size_t out_cap) {
    uint8_t payload[5];
    payload[0] = (uint8_t)(mv_per_cell & 0xFF);
    payload[1] = (uint8_t)((mv_per_cell >> 8) & 0xFF);
    payload[2] = (uint8_t)(duration_min & 0xFF);
    payload[3] = (uint8_t)((duration_min >> 8) & 0xFF);
    payload[4] = enable ? 1 : 0;
    return fr_encode_frame(FR_CMD_SET_EQUALISE, payload, sizeof(payload), out, out_cap);
}

int fr_encode_set_current_limit_pct(uint8_t pct, uint8_t *out, size_t out_cap) {
    if (pct > 100) return -1;
    return fr_encode_frame(FR_CMD_SET_CURRENT_LIMIT_PCT, &pct, 1, out, out_cap);
}

int fr_encode_set_temp_comp(int16_t uv_per_c_per_cell, uint8_t *out, size_t out_cap) {
    uint8_t payload[2];
    uint16_t v = (uint16_t)uv_per_c_per_cell;
    payload[0] = (uint8_t)(v & 0xFF);
    payload[1] = (uint8_t)((v >> 8) & 0xFF);
    return fr_encode_frame(FR_CMD_SET_TEMP_COMP, payload, sizeof(payload), out, out_cap);
}

int fr_encode_get_status(uint8_t *out, size_t out_cap) {
    return fr_encode_frame(FR_CMD_GET_STATUS, NULL, 0, out, out_cap);
}

int fr_encode_heartbeat(uint32_t seq, uint8_t *out, size_t out_cap) {
    uint8_t payload[4];
    payload[0] = (uint8_t)(seq & 0xFF);
    payload[1] = (uint8_t)((seq >> 8) & 0xFF);
    payload[2] = (uint8_t)((seq >> 16) & 0xFF);
    payload[3] = (uint8_t)((seq >> 24) & 0xFF);
    return fr_encode_frame(FR_CMD_HEARTBEAT, payload, sizeof(payload), out, out_cap);
}

int fr_encode_nack(uint8_t code, uint8_t *out, size_t out_cap) {
    return fr_encode_frame(FR_CMD_NACK, &code, 1, out, out_cap);
}

int fr_encode_status(uint8_t mode, uint8_t fault_flags, float v_batt_v, float i_batt_a,
                      float t_batt_c, uint8_t *out, size_t out_cap) {
    uint8_t payload[8];
    /* uint16 v_batt centivolts (unsigned, always >= 0 for a battery pack);
     * int16 i_batt centiamps (signed, +charge/-discharge per CONTRACTS
     * Sec.1); int16 t_batt deci-C (signed). All little-endian. */
    uint16_t v_cv = (uint16_t)(v_batt_v * 100.0f + 0.5f);
    int16_t i_ca = (int16_t)(i_batt_a * 100.0f + (i_batt_a >= 0.0f ? 0.5f : -0.5f));
    int16_t t_dc = (int16_t)(t_batt_c * 10.0f + (t_batt_c >= 0.0f ? 0.5f : -0.5f));
    uint16_t i_ca_u = (uint16_t)i_ca;
    uint16_t t_dc_u = (uint16_t)t_dc;

    payload[0] = mode;
    payload[1] = fault_flags;
    payload[2] = (uint8_t)(v_cv & 0xFF);
    payload[3] = (uint8_t)((v_cv >> 8) & 0xFF);
    payload[4] = (uint8_t)(i_ca_u & 0xFF);
    payload[5] = (uint8_t)((i_ca_u >> 8) & 0xFF);
    payload[6] = (uint8_t)(t_dc_u & 0xFF);
    payload[7] = (uint8_t)((t_dc_u >> 8) & 0xFF);
    return fr_encode_frame(FR_CMD_GET_STATUS, payload, sizeof(payload), out, out_cap);
}

/* --------------------------------------------------------------------
 * Streaming parser -- resync on bad CRC. Mirrors frames.py's
 * FrameParser exactly: any malformed frame (bad CRC, truncated escape,
 * length mismatch) is silently dropped, never aborts/asserts on wire
 * data, and the very next SOF starts a clean frame.
 * -------------------------------------------------------------------- */

void fr_parser_init(fr_parser_t *p) {
    p->buf_len = 0;
    p->in_frame = false;
}

static int fr_try_parse(const uint8_t *stuffed_body, uint16_t stuffed_len, fr_frame_t *out) {
    uint8_t body[2 + FR_MAX_PAYLOAD_LEN + 2];
    int body_len;
    uint16_t ln;
    uint16_t crc_rx, crc_calc;

    body_len = fr_unstuff(stuffed_body, stuffed_len, body, sizeof(body));
    if (body_len < 0) return 0;
    if (body_len < 4) return 0;

    ln = body[1];
    if ((size_t)body_len != (size_t)(2 + ln + 2)) return 0;

    crc_rx = (uint16_t)(body[2 + ln] | ((uint16_t)body[2 + ln + 1] << 8));
    crc_calc = fr_crc16_ccitt(body, (size_t)(2 + ln), 0xFFFFu);
    if (crc_rx != crc_calc) return 0;

    out->cmd = body[0];
    out->payload_len = ln;
    if (ln > 0) memcpy(out->payload, body + 2, ln);
    return 1;
}

int fr_parser_feed_byte(fr_parser_t *p, uint8_t byte, fr_frame_t *out) {
    if (!p->in_frame) {
        if (byte == FR_SOF) {
            p->in_frame = true;
            p->buf_len = 0;
        }
        return 0;
    }
    if (byte == FR_SOF) {
        p->buf_len = 0; /* stray SOF mid-frame: resync onto this new frame */
        return 0;
    }
    if (byte == FR_EOF) {
        int got = fr_try_parse(p->buf, p->buf_len, out);
        p->in_frame = false;
        p->buf_len = 0;
        return got;
    }
    if (p->buf_len < FR_MAX_STUFFED_BODY_LEN) {
        p->buf[p->buf_len++] = byte;
    } else {
        /* runaway frame (missing EOF) -- give up and resync */
        p->in_frame = false;
        p->buf_len = 0;
    }
    return 0;
}

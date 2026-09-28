/* test_frames_host.c -- host C exercise of frames.h/.c.
 *
 * Usage:
 *   ./test_frames_host                 run internal self-tests (encode/decode
 *                                       round-trip incl. byte-stuffing, CRC
 *                                       corruption + resync, streaming parser
 *                                       edge cases); prints PASS/FAIL per
 *                                       check and a summary; exit 0 iff all
 *                                       passed.
 *   ./test_frames_host --vectors FILE  encode each command listed in FILE
 *                                      (see parity_vectors.txt) and print
 *                                      "NAME:HEXBYTES" lines to stdout, one
 *                                      per vector -- for the Python/C parity
 *                                      test (tests/test_charger.py).
 */
#include "frames.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_failures = 0;
#define CHECK(cond, msg)                                                        \
    do {                                                                        \
        if (!(cond)) {                                                          \
            fprintf(stderr, "FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__);   \
            g_failures++;                                                       \
        } else {                                                                \
            fprintf(stderr, "ok:   %s\n", (msg));                               \
        }                                                                       \
    } while (0)

static void hex_print(const uint8_t *buf, int len, char *out) {
    static const char *hexd = "0123456789ABCDEF";
    int i;
    for (i = 0; i < len; i++) {
        out[2 * i] = hexd[(buf[i] >> 4) & 0xF];
        out[2 * i + 1] = hexd[buf[i] & 0xF];
    }
    out[2 * len] = '\0';
}

/* ------------------------------------------------------------------ */
/* Self-tests                                                          */
/* ------------------------------------------------------------------ */

static void test_crc_known_value(void) {
    /* CRC-16/CCITT-FALSE("123456789") == 0x29B1 -- the standard check value
     * for this exact variant (poly 0x1021, init 0xFFFF, no reflect/xorout). */
    const uint8_t msg[] = "123456789";
    uint16_t crc = fr_crc16_ccitt(msg, 9, 0xFFFFu);
    CHECK(crc == 0x29B1u, "crc16_ccitt matches CCITT-FALSE check value 0x29B1");
}

static void test_encode_decode_roundtrip(void) {
    uint8_t frame[FR_MAX_FRAME_LEN];
    int n;
    fr_parser_t p;
    fr_frame_t out;
    int i, got = 0;

    n = fr_encode_set_absorption(2435, 180, frame, sizeof(frame));
    CHECK(n > 0, "encode_set_absorption succeeds");
    CHECK(frame[0] == FR_SOF, "frame starts with SOF");
    CHECK(frame[n - 1] == FR_EOF, "frame ends with EOF");

    fr_parser_init(&p);
    for (i = 0; i < n; i++) {
        if (fr_parser_feed_byte(&p, frame[i], &out)) got = 1;
    }
    CHECK(got == 1, "streaming parser recovers the frame");
    CHECK(out.cmd == FR_CMD_SET_ABSORPTION, "recovered cmd == SET_ABSORPTION");
    CHECK(out.payload_len == 4, "recovered payload_len == 4");
    {
        uint16_t mv = (uint16_t)(out.payload[0] | (out.payload[1] << 8));
        uint16_t timeout = (uint16_t)(out.payload[2] | (out.payload[3] << 8));
        CHECK(mv == 2435, "recovered mv_per_cell == 2435");
        CHECK(timeout == 180, "recovered timeout_min == 180");
    }
}

static void test_stuffing_roundtrip_with_special_bytes(void) {
    /* payload deliberately containing SOF/EOF/ESC bytes */
    uint8_t payload[4] = {FR_SOF, FR_EOF, FR_ESC, 0x00};
    uint8_t frame[FR_MAX_FRAME_LEN];
    int n, i, got = 0;
    fr_parser_t p;
    fr_frame_t out;

    n = fr_encode_frame(FR_CMD_SET_TEMP_COMP, payload, sizeof(payload), frame, sizeof(frame));
    CHECK(n > 0, "encode_frame with SOF/EOF/ESC-laden payload succeeds");

    /* the raw framing bytes (SOF at [0], EOF at [n-1]) must be the only
     * unescaped occurrences; everything strictly between them that equals
     * SOF/EOF must be preceded by an ESC byte. */
    {
        int bad = 0;
        for (i = 1; i < n - 1; i++) {
            if ((frame[i] == FR_SOF || frame[i] == FR_EOF) && frame[i - 1] != FR_ESC) {
                /* frame[i-1] could itself be an escaped byte's second half;
                 * a simpler sufficient check: re-run through the parser
                 * below and confirm exact payload recovery instead. */
                (void)bad;
            }
        }
    }

    fr_parser_init(&p);
    for (i = 0; i < n; i++) {
        if (fr_parser_feed_byte(&p, frame[i], &out)) got = 1;
    }
    CHECK(got == 1, "parser recovers a frame whose payload needed stuffing");
    CHECK(out.payload_len == 4, "stuffed payload_len recovered correctly");
    CHECK(memcmp(out.payload, payload, 4) == 0, "stuffed payload bytes recovered exactly");
}

static void test_bad_crc_then_resync(void) {
    uint8_t frame[FR_MAX_FRAME_LEN];
    int n, i, got_count = 0;
    fr_parser_t p;
    fr_frame_t out;

    n = fr_encode_set_float(2270, frame, sizeof(frame));
    CHECK(n > 3, "encode_set_float succeeds for corruption test");
    /* corrupt one payload byte (index 3 is inside the stuffed body, well
     * clear of SOF/EOF at the ends for this particular short frame). */
    frame[3] ^= 0xFF;

    fr_parser_init(&p);
    for (i = 0; i < n; i++) {
        if (fr_parser_feed_byte(&p, frame[i], &out)) got_count++;
    }
    CHECK(got_count == 0, "corrupted CRC frame is silently dropped, not delivered");

    /* now feed a second, valid frame right after -- parser must resync */
    got_count = 0;
    n = fr_encode_heartbeat(42, frame, sizeof(frame));
    for (i = 0; i < n; i++) {
        if (fr_parser_feed_byte(&p, frame[i], &out)) got_count++;
    }
    CHECK(got_count == 1, "parser resyncs and recovers the next valid frame");
    CHECK(out.cmd == FR_CMD_HEARTBEAT, "resynced frame has the right cmd");
}

static void test_stray_sof_mid_frame(void) {
    uint8_t f1[FR_MAX_FRAME_LEN], f2[FR_MAX_FRAME_LEN];
    int n1, n2, i, got = 0;
    fr_parser_t p;
    fr_frame_t out;

    n1 = fr_encode_set_float(2270, f1, sizeof(f1));
    n2 = fr_encode_heartbeat(7, f2, sizeof(f2));

    fr_parser_init(&p);
    /* feed SOF..middle of f1 (no EOF), then the *entire* second valid frame --
     * the stray SOF at the start of f2 must abandon f1's partial bytes. */
    for (i = 0; i < n1 - 1; i++) {
        fr_parser_feed_byte(&p, f1[i], &out);
    }
    for (i = 0; i < n2; i++) {
        if (fr_parser_feed_byte(&p, f2[i], &out)) got++;
    }
    CHECK(got == 1, "stray SOF mid-frame discards the partial frame and resyncs");
    CHECK(out.cmd == FR_CMD_HEARTBEAT, "recovered frame after stray SOF is the second frame");
}

static void test_hard_ceiling_range_check(void) {
    /* not a codec property, but the documented current-limit range check */
    uint8_t frame[FR_MAX_FRAME_LEN];
    int n = fr_encode_set_current_limit_pct(101, frame, sizeof(frame));
    CHECK(n < 0, "fr_encode_set_current_limit_pct rejects > 100");
}

static void run_self_tests(void) {
    test_crc_known_value();
    test_encode_decode_roundtrip();
    test_stuffing_roundtrip_with_special_bytes();
    test_bad_crc_then_resync();
    test_stray_sof_mid_frame();
    test_hard_ceiling_range_check();
}

/* ------------------------------------------------------------------ */
/* --vectors mode: emit NAME:HEX lines for the Python parity check     */
/* ------------------------------------------------------------------ */

static int emit_vectors(const char *path) {
    FILE *f = fopen(path, "r");
    char line[256];
    if (!f) {
        fprintf(stderr, "cannot open vectors file: %s\n", path);
        return 1;
    }
    while (fgets(line, sizeof(line), f)) {
        char name[64];
        long a1 = 0, a2 = 0, a3 = 0;
        int nfields;
        uint8_t frame[FR_MAX_FRAME_LEN];
        char hex[2 * FR_MAX_FRAME_LEN + 1];
        int n = -1;

        /* strip comment/blank lines */
        {
            char *p = line;
            while (*p == ' ' || *p == '\t') p++;
            if (*p == '#' || *p == '\n' || *p == '\0') continue;
        }

        nfields = sscanf(line, "%63s %ld %ld %ld", name, &a1, &a2, &a3);
        if (nfields < 1) continue;

        if (strcmp(name, "SET_FLOAT") == 0) {
            n = fr_encode_set_float((uint16_t)a1, frame, sizeof(frame));
        } else if (strcmp(name, "SET_ABSORPTION") == 0) {
            n = fr_encode_set_absorption((uint16_t)a1, (uint16_t)a2, frame, sizeof(frame));
        } else if (strcmp(name, "SET_EQUALISE") == 0) {
            n = fr_encode_set_equalise((uint16_t)a1, (uint16_t)a2, a3 != 0, frame, sizeof(frame));
        } else if (strcmp(name, "SET_CURRENT_LIMIT_PCT") == 0) {
            n = fr_encode_set_current_limit_pct((uint8_t)a1, frame, sizeof(frame));
        } else if (strcmp(name, "SET_TEMP_COMP") == 0) {
            n = fr_encode_set_temp_comp((int16_t)a1, frame, sizeof(frame));
        } else if (strcmp(name, "GET_STATUS") == 0) {
            n = fr_encode_get_status(frame, sizeof(frame));
        } else if (strcmp(name, "HEARTBEAT") == 0) {
            n = fr_encode_heartbeat((uint32_t)a1, frame, sizeof(frame));
        } else if (strcmp(name, "NACK") == 0) {
            n = fr_encode_nack((uint8_t)a1, frame, sizeof(frame));
        } else {
            fprintf(stderr, "unknown vector command: %s\n", name);
            fclose(f);
            return 1;
        }

        if (n < 0) {
            fprintf(stderr, "encode failed for vector: %s", line);
            fclose(f);
            return 1;
        }
        hex_print(frame, n, hex);
        printf("%s:%s\n", name, hex);
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[1], "--vectors") == 0) {
        return emit_vectors(argv[2]);
    }

    run_self_tests();
    if (g_failures == 0) {
        fprintf(stderr, "\nALL CHECKS PASSED\n");
        return 0;
    }
    fprintf(stderr, "\n%d CHECK(S) FAILED\n", g_failures);
    return 1;
}

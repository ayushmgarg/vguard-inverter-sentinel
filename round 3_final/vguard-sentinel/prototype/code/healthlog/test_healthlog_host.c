/* test_healthlog_host.c — host C exercise of healthlog.h/.c.
 *
 * Builds a signed chain using a software ECDSA-P256 key as the hl_sign_cb backend (standing
 * in for the ATECC608 in production, per 09 §4 and healthlog.h's doc comment), self-verifies
 * it with hl_verify_chain, and writes the chain + raw public key out to files so that
 * tests/test_healthlog.py can cross-verify this C-produced chain from Python (and, when
 * hl_verify_chain has real signature checking i.e. HL_USE_OPENSSL, sign a Python-produced
 * chain is NOT done here — that direction is exercised by tests/test_healthlog.py calling
 * this same pubkey/chain files it already writes; the "vice versa" is Python producing a
 * chain that this binary's hl_verify_chain checks, done in --verify mode below).
 *
 * Usage:
 *   ./test_healthlog_host                       run the full self-test, write chain/pubkey
 *   ./test_healthlog_host --verify CHAIN PUBKEY  verify an externally-produced chain
 *                                                 (used by pytest to check the C verifier
 *                                                 against a Python-produced chain)
 */
#include "healthlog.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef HL_USE_OPENSSL
#include <openssl/bn.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>
#else
#include "sha256.h"
#endif

#define CHAIN_OUT "chain_from_c.bin"
#define PUBKEY_OUT "pubkey_from_c.bin"
#define CHECKPOINT_OUT "checkpoint_from_c.bin"

static int g_failures = 0;
#define CHECK(cond, msg)                                                                  \
    do {                                                                                  \
        if (!(cond)) {                                                                    \
            fprintf(stderr, "FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__);             \
            g_failures++;                                                                 \
        } else {                                                                          \
            fprintf(stderr, "ok:   %s\n", (msg));                                         \
        }                                                                                 \
    } while (0)

static int read_file(const char *path, uint8_t **out, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz < 0) { fclose(f); return -1; }
    uint8_t *buf = (uint8_t *)malloc((size_t)sz > 0 ? (size_t)sz : 1);
    size_t nread = sz > 0 ? fread(buf, 1, (size_t)sz, f) : 0;
    fclose(f);
    if (nread != (size_t)sz) { free(buf); return -1; }
    *out = buf;
    *out_len = (size_t)sz;
    return 0;
}

static int write_file(const char *path, const uint8_t *buf, size_t len) {
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    size_t n = fwrite(buf, 1, len, f);
    fclose(f);
    return n == len ? 0 : -1;
}

#ifdef HL_USE_OPENSSL

static int openssl_sign_cb(const uint8_t hash32[HL_HASH_SIZE], uint8_t sig64[HL_SIG_SIZE], void *ctx_) {
    EC_KEY *key = (EC_KEY *)ctx_;
    ECDSA_SIG *sig = ECDSA_do_sign(hash32, (int)HL_HASH_SIZE, key);
    if (!sig) return 1;
    const BIGNUM *r = NULL, *s = NULL;
    ECDSA_SIG_get0(sig, &r, &s);
    memset(sig64, 0, HL_SIG_SIZE);
    BN_bn2binpad(r, sig64, 32);
    BN_bn2binpad(s, sig64 + 32, 32);
    ECDSA_SIG_free(sig);
    return 0;
}

static int export_pubkey_raw(EC_KEY *key, uint8_t out[HL_PUBKEY_SIZE]) {
    const EC_GROUP *group = EC_KEY_get0_group(key);
    const EC_POINT *point = EC_KEY_get0_public_key(key);
    uint8_t buf[65];
    size_t n = EC_POINT_point2oct(group, point, POINT_CONVERSION_UNCOMPRESSED, buf, sizeof(buf), NULL);
    if (n != 65 || buf[0] != 0x04) return -1;
    memcpy(out, buf + 1, HL_PUBKEY_SIZE);
    return 0;
}

static int run_self_test(void) {
    EC_KEY *key = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    CHECK(key != NULL, "EC_KEY_new_by_curve_name");
    if (!key) return 1;
    CHECK(EC_KEY_generate_key(key) == 1, "EC_KEY_generate_key");

    uint8_t pubkey[HL_PUBKEY_SIZE];
    CHECK(export_pubkey_raw(key, pubkey) == 0, "export_pubkey_raw");

    static uint8_t storage[1 << 16];
    hl_t hl;
    CHECK(hl_init(&hl, storage, sizeof(storage), openssl_sign_cb, key) == HL_OK, "hl_init");

    const char *fw = "1.2.3";
    uint8_t cap_sample[4] = {80, 0, 0, 0}; /* toy payload: 80% SoH */
    uint8_t grade[1] = {2};                /* toy: DEGRADING */

    CHECK(hl_append(&hl, HL_EVT_FW_VERSION, (const uint8_t *)fw, strlen(fw)) == HL_OK, "append FW_VERSION (genesis)");
    CHECK(hl_append(&hl, HL_EVT_CAPACITY_SAMPLE, cap_sample, sizeof(cap_sample)) == HL_OK, "append CAPACITY_SAMPLE");
    CHECK(hl_append(&hl, HL_EVT_GRADE_CHANGE, grade, sizeof(grade)) == HL_OK, "append GRADE_CHANGE");
    CHECK(hl_append(&hl, HL_EVT_ANOMALY, NULL, 0) == HL_OK, "append ANOMALY (empty payload)");

    CHECK(hl.next_counter == 4, "counter advanced to 4");
    CHECK(hl_length(&hl) == 3 * (HL_RECORD_OVERHEAD) + HL_RECORD_OVERHEAD + strlen(fw) + sizeof(cap_sample) + sizeof(grade),
          "total length matches expected record sizes");

    int ok = hl_verify_chain(hl.buf, hl.len, pubkey);
    CHECK(ok == 1, "hl_verify_chain accepts the freshly written chain");

    size_t n_ok = 0;
    int64_t bad = -2;
    char reason[128];
    int ok2 = hl_verify_chain_detail(hl.buf, hl.len, pubkey, &n_ok, &bad, reason, sizeof(reason));
    CHECK(ok2 == 1 && n_ok == 4 && bad == -1, "hl_verify_chain_detail reports 4 good records, no bad index");
    fprintf(stderr, "      verify_chain_detail reason: %s\n", reason);

    /* Tamper: flip a byte inside record 1's payload and confirm detection. */
    uint8_t *tampered = (uint8_t *)malloc(hl.len);
    memcpy(tampered, hl.buf, hl.len);
    tampered[HL_HEADER_SIZE + 3] ^= 0xFF; /* inside FW_VERSION payload */
    int tampered_ok = hl_verify_chain(tampered, hl.len, pubkey);
    CHECK(tampered_ok == 0, "hl_verify_chain rejects a tampered byte");
    free(tampered);

    /* Deletion: drop the second record's bytes, causing a counter gap for what follows. */
    /* record 0 length: HL_RECORD_OVERHEAD + strlen(fw); record 1 length: HL_RECORD_OVERHEAD + 4 */
    size_t rec0_len = HL_RECORD_OVERHEAD + strlen(fw);
    size_t rec1_len = HL_RECORD_OVERHEAD + sizeof(cap_sample);
    size_t deleted_len = hl.len - rec1_len;
    uint8_t *deleted = (uint8_t *)malloc(deleted_len);
    memcpy(deleted, hl.buf, rec0_len);
    memcpy(deleted + rec0_len, hl.buf + rec0_len + rec1_len, hl.len - rec0_len - rec1_len);
    int deleted_ok = hl_verify_chain(deleted, deleted_len, pubkey);
    CHECK(deleted_ok == 0, "hl_verify_chain rejects a deleted middle record (counter gap)");
    free(deleted);

    /* Checkpoint (format.md §8): sign an attestation of hl's current head (4 records,
     * last_counter == 3) and confirm it verifies against the exact chain bytes we're about
     * to write out — this is the pairing tests/test_healthlog.py cross-verifies from
     * Python (CHAIN_OUT + CHECKPOINT_OUT together). */
    hl_checkpoint_t ckpt;
    CHECK(hl_checkpoint(&hl, &ckpt) == HL_OK, "hl_checkpoint produces a checkpoint");
    CHECK(ckpt.last_counter == 3, "checkpoint last_counter matches hl's current head (3)");

    int ckpt_ok = hl_verify_chain_ckpt(hl.buf, hl.len, pubkey, &ckpt);
    CHECK(ckpt_ok == 1, "hl_verify_chain_ckpt accepts checkpoint against its own chain");

    /* Tamper the checkpoint signature and confirm rejection. */
    hl_checkpoint_t ckpt_bad_sig = ckpt;
    ckpt_bad_sig.sig[0] ^= 0xFF;
    char ckpt_reason[128];
    int ckpt_bad_sig_ok = hl_verify_chain_ckpt_detail(hl.buf, hl.len, pubkey, &ckpt_bad_sig,
                                                       ckpt_reason, sizeof(ckpt_reason));
    CHECK(ckpt_bad_sig_ok == 0, "hl_verify_chain_ckpt rejects a tampered checkpoint signature");

    /* A chain cut back to just the first record is shorter than the checkpoint's
     * last_counter (3) — must be reported as TRUNCATED. */
    int ckpt_trunc_ok = hl_verify_chain_ckpt_detail(hl.buf, rec0_len, pubkey, &ckpt,
                                                     ckpt_reason, sizeof(ckpt_reason));
    CHECK(ckpt_trunc_ok == 0 && strstr(ckpt_reason, "TRUNCATED") != NULL,
          "hl_verify_chain_ckpt reports TRUNCATED for a chain shorter than the checkpoint");

    /* Resume: reopen the log via hl_resume_verified over the same bytes and append one more. */
    static uint8_t storage2[1 << 16];
    memcpy(storage2, hl.buf, hl.len);
    hl_t hl2;
    int rr = hl_resume_verified(&hl2, storage2, hl.len, sizeof(storage2), openssl_sign_cb, key, pubkey);
    CHECK(rr == HL_OK, "hl_resume_verified accepts the valid chain");
    CHECK(hl2.next_counter == 4, "resumed counter continues from 4");
    CHECK(hl_append(&hl2, HL_EVT_MODEL_VERSION, (const uint8_t *)"m1", 2) == HL_OK, "append after resume");
    CHECK(hl_verify_chain(hl2.buf, hl2.len, pubkey) == 1, "chain still verifies after resume+append");

    /* Write chain + pubkey + checkpoint for Python cross-verification
     * (tests/test_healthlog.py). */
    CHECK(write_file(CHAIN_OUT, hl.buf, hl.len) == 0, "write " CHAIN_OUT);
    CHECK(write_file(PUBKEY_OUT, pubkey, HL_PUBKEY_SIZE) == 0, "write " PUBKEY_OUT);
    {
        uint8_t ckpt_bytes[HL_CHECKPOINT_SIZE];
        hl_checkpoint_serialize(&ckpt, ckpt_bytes);
        CHECK(write_file(CHECKPOINT_OUT, ckpt_bytes, sizeof(ckpt_bytes)) == 0, "write " CHECKPOINT_OUT);
    }

    EC_KEY_free(key);
    return g_failures;
}

#else /* !HL_USE_OPENSSL */

static int run_self_test(void) {
    fprintf(stderr,
            "built without OpenSSL/libcrypto (HL_USE_OPENSSL not defined): ECDSA is a "
            "callback-only hook with no bundled implementation, so this harness cannot "
            "produce or verify real signatures. Running the SHA-256-only self-test "
            "instead (hash-chain framing correctness), and skipping the signed-chain / "
            "cross-verification test. See README.md \"Limits\".\n");

    uint8_t out[32];
    hl_sha256((const uint8_t *)"abc", 3, out);
    static const uint8_t expected[32] = {
        0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40, 0xde,
        0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
        0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad,
    };
    CHECK(memcmp(out, expected, 32) == 0, "bundled sha256(\"abc\") matches known-answer test");
    return g_failures;
}

#endif

static int run_verify_mode(const char *chain_path, const char *pubkey_path) {
    uint8_t *chain = NULL, *pubkey = NULL;
    size_t chain_len = 0, pubkey_len = 0;
    if (read_file(chain_path, &chain, &chain_len) != 0) {
        fprintf(stderr, "cannot read chain file: %s\n", chain_path);
        return 1;
    }
    if (read_file(pubkey_path, &pubkey, &pubkey_len) != 0 || pubkey_len != HL_PUBKEY_SIZE) {
        fprintf(stderr, "cannot read %zu-byte pubkey file: %s\n", (size_t)HL_PUBKEY_SIZE, pubkey_path);
        free(chain);
        return 1;
    }
    int ok = hl_verify_chain(chain, chain_len, pubkey);
    size_t n_ok = 0;
    int64_t bad = -2;
    char reason[128];
    hl_verify_chain_detail(chain, chain_len, pubkey, &n_ok, &bad, reason, sizeof(reason));
    printf("hl_verify_chain: %s (n_records_ok=%zu first_bad_index=%lld reason=%s)\n",
           ok == 1 ? "OK" : "FAIL", n_ok, (long long)bad, reason);
    free(chain);
    free(pubkey);
    return ok == 1 ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "--verify") == 0) {
        return run_verify_mode(argv[2], argv[3]);
    }
    if (argc != 1) {
        fprintf(stderr, "usage: %s | %s --verify CHAIN PUBKEY\n", argv[0], argv[0]);
        return 2;
    }
    int failures = run_self_test();
    if (failures) {
        fprintf(stderr, "\n%d check(s) FAILED\n", failures);
        return 1;
    }
    fprintf(stderr, "\nall checks passed\n");
    return 0;
}

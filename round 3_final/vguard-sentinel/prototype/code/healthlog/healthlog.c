/* healthlog.c — see healthlog.h and format.md for the format/API contract. C99. */
#include "healthlog.h"

#include <stdio.h>
#include <string.h>

#ifdef HL_USE_OPENSSL
#include <openssl/bn.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/evp.h>
#include <openssl/obj_mac.h>
#else
#include "sha256.h"
#endif

/* ---- byte helpers: explicit little-endian pack/unpack, no reliance on struct layout /
 * host endianness (format.md §1). ------------------------------------------------------ */

static void put_u32le(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v);       p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static void put_u64le(uint8_t *p, uint64_t v) {
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static void put_u16le(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v); p[1] = (uint8_t)(v >> 8);
}
static uint32_t get_u32le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t get_u64le(const uint8_t *p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; i++) v |= ((uint64_t)p[i]) << (8 * i);
    return v;
}
static uint16_t get_u16le(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

/* Host-default millisecond clock; declared here, defined at the bottom of this file.
 * Overridable by re-linking a different hl_now_ms in a firmware build (glue layer would
 * supply DS3231 time, 10 §6) — not `static`, precisely so it can be overridden. */
uint64_t hl_now_ms(void);

/* ---- ECDSA-P256 verify backend ---------------------------------------------------------
 * Only compiled when HL_USE_OPENSSL is set (Makefile auto-detects libcrypto). Without
 * OpenSSL, this module has no ECDSA implementation of its own (per the task brief: SHA-256
 * is self-rolled as a fallback, but ECDSA stays a callback-only hook) — hl_verify_chain then
 * falls back to hash-chain-only verification and reports that reduced guarantee; see
 * README "Limits".
 */
#ifdef HL_USE_OPENSSL
static int ecdsa_verify_raw(const uint8_t pubkey[HL_PUBKEY_SIZE], const uint8_t hash32[HL_HASH_SIZE],
                             const uint8_t sig64[HL_SIG_SIZE]) {
    int ok = 0;
    uint8_t point_oct[65];
    point_oct[0] = 0x04;
    memcpy(point_oct + 1, pubkey, 64);

    EC_KEY *eckey = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    if (!eckey) return 0;
    const EC_GROUP *group = EC_KEY_get0_group(eckey);
    EC_POINT *point = EC_POINT_new(group);
    if (!point) { EC_KEY_free(eckey); return 0; }

    if (EC_POINT_oct2point(group, point, point_oct, sizeof(point_oct), NULL) != 1) goto done;
    if (EC_KEY_set_public_key(eckey, point) != 1) goto done;

    {
        BIGNUM *r = BN_bin2bn(sig64, 32, NULL);
        BIGNUM *s = BN_bin2bn(sig64 + 32, 32, NULL);
        ECDSA_SIG *sig = ECDSA_SIG_new();
        if (r && s && sig) {
            /* ECDSA_SIG_set0 takes ownership of r, s on success */
            if (ECDSA_SIG_set0(sig, r, s) == 1) {
                ok = (ECDSA_do_verify(hash32, (int)HL_HASH_SIZE, sig, eckey) == 1);
            } else {
                BN_free(r);
                BN_free(s);
            }
        } else {
            if (r) BN_free(r);
            if (s) BN_free(s);
        }
        if (sig) ECDSA_SIG_free(sig);
    }

done:
    EC_POINT_free(point);
    EC_KEY_free(eckey);
    return ok;
}
#endif

static int hl_verify_sig(const uint8_t pubkey[HL_PUBKEY_SIZE], const uint8_t hash32[HL_HASH_SIZE],
                          const uint8_t sig64[HL_SIG_SIZE]) {
#ifdef HL_USE_OPENSSL
    return ecdsa_verify_raw(pubkey, hash32, sig64);
#else
    (void)pubkey; (void)hash32; (void)sig64;
    return -1; /* "unavailable", distinct from 0 ("checked and failed") */
#endif
}

/* ---- record framing --------------------------------------------------------------------
 * Serializes/parses exactly the layout in format.md §2. Never assumes struct packing.
 */

typedef struct {
    uint32_t counter;
    uint64_t ts_ms;
    uint16_t type;
    uint16_t len;
    const uint8_t *payload;   /* points into caller's buffer, not owned */
    const uint8_t *prev_hash; /* points into caller's buffer, 32 bytes */
    const uint8_t *sig;       /* points into caller's buffer, 64 bytes */
} hl_record_view_t;

/* Parse one record at buf[offset..n). Returns the offset just past the record on success,
 * or 0 on failure (never a valid "just past header" offset since HL_HEADER_SIZE > 0). */
static size_t parse_record_at(const uint8_t *buf, size_t n, size_t offset, hl_record_view_t *out) {
    if (offset + HL_HEADER_SIZE > n) return 0;
    uint32_t counter = get_u32le(buf + offset);
    uint64_t ts_ms = get_u64le(buf + offset + 4);
    uint16_t type = get_u16le(buf + offset + 12);
    uint16_t len = get_u16le(buf + offset + 14);

    size_t o = offset + HL_HEADER_SIZE;
    size_t end_payload = o + len;
    size_t end_prev = end_payload + HL_HASH_SIZE;
    size_t end_sig = end_prev + HL_SIG_SIZE;
    if (end_sig > n) return 0; /* truncated */

    out->counter = counter;
    out->ts_ms = ts_ms;
    out->type = type;
    out->len = len;
    out->payload = buf + o;
    out->prev_hash = buf + end_payload;
    out->sig = buf + end_prev;
    return end_sig;
}

/* Recompute this record's own hash (header||payload||prev_hash), matching format.md §3.
 * Uses a small on-stack scratch buffer sized for the header; payload/prev_hash are hashed
 * incrementally where the backend supports it, falling back to a heap-free two-call
 * approach that still avoids any malloc. */
static void hash_record(const hl_record_view_t *rec, uint8_t out[HL_HASH_SIZE]) {
    uint8_t header[HL_HEADER_SIZE];
    put_u32le(header, rec->counter);
    put_u64le(header + 4, rec->ts_ms);
    put_u16le(header + 12, rec->type);
    put_u16le(header + 14, rec->len);

#ifdef HL_USE_OPENSSL
    EVP_MD_CTX *mdctx = EVP_MD_CTX_new();
    unsigned int outlen = 0;
    EVP_DigestInit_ex(mdctx, EVP_sha256(), NULL);
    EVP_DigestUpdate(mdctx, header, HL_HEADER_SIZE);
    if (rec->len) EVP_DigestUpdate(mdctx, rec->payload, rec->len);
    EVP_DigestUpdate(mdctx, rec->prev_hash, HL_HASH_SIZE);
    EVP_DigestFinal_ex(mdctx, out, &outlen);
    EVP_MD_CTX_free(mdctx);
#else
    hl_sha256_ctx_t ctx;
    hl_sha256_init(&ctx);
    hl_sha256_update(&ctx, header, HL_HEADER_SIZE);
    if (rec->len) hl_sha256_update(&ctx, rec->payload, rec->len);
    hl_sha256_update(&ctx, rec->prev_hash, HL_HASH_SIZE);
    hl_sha256_final(&ctx, out);
#endif
}

/* Generic SHA-256 over an arbitrary byte range, used by checkpoints (which hash a small
 * fixed-layout struct rather than a record) — factored out of hash_record's backend
 * selection so both share the same OpenSSL/bundled-sha256 switch. */
static void hl_sha256_bytes(const uint8_t *data, size_t len, uint8_t out[HL_HASH_SIZE]) {
#ifdef HL_USE_OPENSSL
    EVP_MD_CTX *mdctx = EVP_MD_CTX_new();
    unsigned int outlen = 0;
    EVP_DigestInit_ex(mdctx, EVP_sha256(), NULL);
    EVP_DigestUpdate(mdctx, data, len);
    EVP_DigestFinal_ex(mdctx, out, &outlen);
    EVP_MD_CTX_free(mdctx);
#else
    hl_sha256_ctx_t ctx;
    hl_sha256_init(&ctx);
    hl_sha256_update(&ctx, data, len);
    hl_sha256_final(&ctx, out);
#endif
}

/* Pack the 44-byte checkpoint signed payload: last_counter(4 LE) || ts_ms(8 LE) ||
 * head_hash(32) — format.md §8. */
static void checkpoint_signed_bytes(uint32_t last_counter, uint64_t ts_ms,
                                     const uint8_t head_hash[HL_HASH_SIZE],
                                     uint8_t out[4 + 8 + HL_HASH_SIZE]) {
    put_u32le(out, last_counter);
    put_u64le(out + 4, ts_ms);
    memcpy(out + 12, head_hash, HL_HASH_SIZE);
}

/* ---- writer API ------------------------------------------------------------------------ */

int hl_init(hl_t *hl, uint8_t *buf, size_t cap, hl_sign_cb sign_cb, void *sign_ctx) {
    if (!hl || !buf || !sign_cb) return HL_ERR_BAD_ARGS;
    hl->buf = buf;
    hl->cap = cap;
    hl->len = 0;
    hl->next_counter = 0;
    memset(hl->last_hash, 0, HL_HASH_SIZE);
    hl->sign_cb = sign_cb;
    hl->sign_ctx = sign_ctx;
    return HL_OK;
}

static int resume_common(hl_t *hl, uint8_t *buf, size_t existing_len, size_t cap,
                          hl_sign_cb sign_cb, void *sign_ctx, const uint8_t *pubkey) {
    if (!hl || !buf || !sign_cb || existing_len > cap) return HL_ERR_BAD_ARGS;

    uint8_t running_hash[HL_HASH_SIZE];
    memset(running_hash, 0, HL_HASH_SIZE);
    uint32_t expected_counter = 0;
    size_t offset = 0;

    while (offset < existing_len) {
        hl_record_view_t rec;
        size_t next = parse_record_at(buf, existing_len, offset, &rec);
        if (next == 0) return HL_ERR_CORRUPT; /* truncated record */
        if (rec.counter != expected_counter) return HL_ERR_CORRUPT; /* gap/reorder */
        if (memcmp(rec.prev_hash, running_hash, HL_HASH_SIZE) != 0) return HL_ERR_CORRUPT;

        uint8_t h[HL_HASH_SIZE];
        hash_record(&rec, h);

        if (pubkey) {
            int v = hl_verify_sig(pubkey, h, rec.sig);
            if (v != 1) return HL_ERR_CORRUPT;
        }

        memcpy(running_hash, h, HL_HASH_SIZE);
        expected_counter++;
        offset = next;
    }

    hl->buf = buf;
    hl->cap = cap;
    hl->len = existing_len;
    hl->next_counter = expected_counter;
    memcpy(hl->last_hash, running_hash, HL_HASH_SIZE);
    hl->sign_cb = sign_cb;
    hl->sign_ctx = sign_ctx;
    return HL_OK;
}

int hl_resume(hl_t *hl, uint8_t *buf, size_t existing_len, size_t cap,
              hl_sign_cb sign_cb, void *sign_ctx) {
    return resume_common(hl, buf, existing_len, cap, sign_cb, sign_ctx, NULL);
}

int hl_resume_verified(hl_t *hl, uint8_t *buf, size_t existing_len, size_t cap,
                        hl_sign_cb sign_cb, void *sign_ctx, const uint8_t pubkey[HL_PUBKEY_SIZE]) {
    if (!pubkey) return HL_ERR_BAD_ARGS;
    return resume_common(hl, buf, existing_len, cap, sign_cb, sign_ctx, pubkey);
}

int hl_append(hl_t *hl, uint16_t type, const uint8_t *payload, size_t n) {
    if (!hl || (n && !payload)) return HL_ERR_BAD_ARGS;
    if (n > 0xFFFFu) return HL_ERR_PAYLOAD_TOO_BIG;

    size_t record_size = HL_RECORD_OVERHEAD + n;
    if (hl->len + record_size > hl->cap) return HL_ERR_NOMEM;

    uint8_t *rec_start = hl->buf + hl->len;
    put_u32le(rec_start, hl->next_counter);
    put_u64le(rec_start + 4, 0 /* filled below once we have a timestamp source */);
    put_u16le(rec_start + 12, type);
    put_u16le(rec_start + 14, (uint16_t)n);
    /* Timestamp: ts_ms comes from hl_now_ms() (declared above, defined at the bottom of
     * this file) so the wire format itself makes no assumption about the time source; the
     * firmware glue layer would override hl_now_ms with DS3231 time (10 §6). */
    put_u64le(rec_start + 4, hl_now_ms());
    if (n) memcpy(rec_start + HL_HEADER_SIZE, payload, n);
    memcpy(rec_start + HL_HEADER_SIZE + n, hl->last_hash, HL_HASH_SIZE);

    hl_record_view_t rec;
    rec.counter = hl->next_counter;
    rec.ts_ms = get_u64le(rec_start + 4);
    rec.type = type;
    rec.len = (uint16_t)n;
    rec.payload = rec_start + HL_HEADER_SIZE;
    rec.prev_hash = rec_start + HL_HEADER_SIZE + n;

    uint8_t digest[HL_HASH_SIZE];
    hash_record(&rec, digest);

    uint8_t sig[HL_SIG_SIZE];
    if (hl->sign_cb(digest, sig, hl->sign_ctx) != 0) return HL_ERR_SIGN_FAILED;

    memcpy(rec_start + HL_HEADER_SIZE + n + HL_HASH_SIZE, sig, HL_SIG_SIZE);

    hl->len += record_size;
    hl->next_counter += 1;
    memcpy(hl->last_hash, digest, HL_HASH_SIZE);
    return HL_OK;
}

size_t hl_length(const hl_t *hl) {
    return hl ? hl->len : 0;
}

/* ---- checkpoints (healthlog.h, format.md §8) -------------------------------------------- */

int hl_checkpoint(hl_t *hl, hl_checkpoint_t *out) {
    if (!hl || !out || !hl->sign_cb) return HL_ERR_BAD_ARGS;
    if (hl->next_counter == 0) return HL_ERR_BAD_ARGS; /* nothing appended yet to checkpoint */

    uint32_t last_counter = hl->next_counter - 1;
    uint64_t ts_ms = hl_now_ms();

    uint8_t signed_bytes[4 + 8 + HL_HASH_SIZE];
    checkpoint_signed_bytes(last_counter, ts_ms, hl->last_hash, signed_bytes);

    uint8_t digest[HL_HASH_SIZE];
    hl_sha256_bytes(signed_bytes, sizeof(signed_bytes), digest);

    uint8_t sig[HL_SIG_SIZE];
    if (hl->sign_cb(digest, sig, hl->sign_ctx) != 0) return HL_ERR_SIGN_FAILED;

    out->last_counter = last_counter;
    out->ts_ms = ts_ms;
    memcpy(out->head_hash, hl->last_hash, HL_HASH_SIZE);
    memcpy(out->sig, sig, HL_SIG_SIZE);
    return HL_OK;
}

void hl_checkpoint_serialize(const hl_checkpoint_t *ckpt, uint8_t out[HL_CHECKPOINT_SIZE]) {
    put_u32le(out, ckpt->last_counter);
    put_u64le(out + 4, ckpt->ts_ms);
    memcpy(out + 12, ckpt->head_hash, HL_HASH_SIZE);
    memcpy(out + 12 + HL_HASH_SIZE, ckpt->sig, HL_SIG_SIZE);
}

int hl_checkpoint_parse(const uint8_t *buf, size_t n, hl_checkpoint_t *out) {
    if (!buf || !out || n < HL_CHECKPOINT_SIZE) return HL_ERR_BAD_ARGS;
    out->last_counter = get_u32le(buf);
    out->ts_ms = get_u64le(buf + 4);
    memcpy(out->head_hash, buf + 12, HL_HASH_SIZE);
    memcpy(out->sig, buf + 12 + HL_HASH_SIZE, HL_SIG_SIZE);
    return HL_OK;
}

/* ---- verifier API ------------------------------------------------------------------------ */

int hl_verify_chain_detail(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                            size_t *n_records_ok, int64_t *first_bad_index,
                            char *reason, size_t reason_cap) {
    size_t ok_count = 0;
    uint8_t running_hash[HL_HASH_SIZE];
    memset(running_hash, 0, HL_HASH_SIZE);
    uint32_t expected_counter = 0;
    size_t offset = 0;
    int result = 1;
    int64_t bad_index = -1;
    const char *why = "ok";
#ifndef HL_USE_OPENSSL
    int sig_unverifiable_seen = 0;
#endif

    if (!buf || !pubkey) {
        result = 0; bad_index = 0; why = "bad arguments";
        goto done;
    }

    while (offset < n) {
        hl_record_view_t rec;
        size_t next = parse_record_at(buf, n, offset, &rec);
        if (next == 0) {
            result = 0; bad_index = (int64_t)expected_counter;
            why = "truncated record";
            break;
        }
        if (rec.counter != expected_counter) {
            result = 0; bad_index = (int64_t)expected_counter;
            why = "counter gap or reorder";
            break;
        }
        if (memcmp(rec.prev_hash, running_hash, HL_HASH_SIZE) != 0) {
            result = 0; bad_index = (int64_t)expected_counter;
            why = "hash chain broken (tamper, reorder, or replay)";
            break;
        }

        uint8_t h[HL_HASH_SIZE];
        hash_record(&rec, h);

        int v = hl_verify_sig(pubkey, h, rec.sig);
        if (v == 0) {
            result = 0; bad_index = (int64_t)expected_counter;
            why = "signature verification failed (tamper)";
            break;
        }
#ifndef HL_USE_OPENSSL
        if (v < 0) sig_unverifiable_seen = 1; /* no ECDSA backend; hash-chain-only check */
#endif

        memcpy(running_hash, h, HL_HASH_SIZE);
        expected_counter++;
        ok_count++;
        offset = next;
    }

#ifndef HL_USE_OPENSSL
    if (result == 1 && sig_unverifiable_seen) {
        why = "hash chain OK; signatures NOT checked (built without OpenSSL/libcrypto)";
    }
#endif

done:
    if (n_records_ok) *n_records_ok = ok_count;
    if (first_bad_index) *first_bad_index = bad_index;
    if (reason && reason_cap) {
        size_t l = strlen(why);
        if (l >= reason_cap) l = reason_cap - 1;
        memcpy(reason, why, l);
        reason[l] = '\0';
    }
    return result;
}

int hl_verify_chain(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE]) {
    return hl_verify_chain_detail(buf, n, pubkey, NULL, NULL, NULL, 0);
}

int hl_verify_chain_ckpt_detail(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                                 const hl_checkpoint_t *ckpt, char *reason, size_t reason_cap) {
    const char *why = "ok";
    int result = 1;

    if (!buf || !pubkey || !ckpt) {
        result = 0; why = "bad arguments";
        goto done;
    }

    /* (a) the checkpoint's own signature must verify against pubkey. */
    {
        uint8_t signed_bytes[4 + 8 + HL_HASH_SIZE];
        checkpoint_signed_bytes(ckpt->last_counter, ckpt->ts_ms, ckpt->head_hash, signed_bytes);
        uint8_t digest[HL_HASH_SIZE];
        hl_sha256_bytes(signed_bytes, sizeof(signed_bytes), digest);
        int v = hl_verify_sig(pubkey, digest, ckpt->sig);
        if (v == 0) {
            result = 0; why = "checkpoint signature invalid";
            goto done;
        }
    }

    /* (c)+(b)+(d): walk the whole chain (same checks as hl_verify_chain_detail), tracking
     * the hash of the record at counter == ckpt->last_counter as we pass it. */
    {
        uint8_t running_hash[HL_HASH_SIZE];
        memset(running_hash, 0, HL_HASH_SIZE);
        uint32_t expected_counter = 0;
        size_t offset = 0;
        uint8_t head_hash_at_ckpt[HL_HASH_SIZE];
        int have_head_hash_at_ckpt = 0;

        while (offset < n) {
            hl_record_view_t rec;
            size_t next = parse_record_at(buf, n, offset, &rec);
            if (next == 0) {
                result = 0; why = "truncated record";
                goto done;
            }
            if (rec.counter != expected_counter) {
                result = 0; why = "counter gap or reorder";
                goto done;
            }
            if (memcmp(rec.prev_hash, running_hash, HL_HASH_SIZE) != 0) {
                result = 0; why = "hash chain broken (tamper, reorder, or replay)";
                goto done;
            }

            uint8_t h[HL_HASH_SIZE];
            hash_record(&rec, h);
            int v = hl_verify_sig(pubkey, h, rec.sig);
            if (v == 0) {
                result = 0; why = "signature verification failed (tamper)";
                goto done;
            }

            memcpy(running_hash, h, HL_HASH_SIZE);
            if (expected_counter == ckpt->last_counter) {
                memcpy(head_hash_at_ckpt, h, HL_HASH_SIZE);
                have_head_hash_at_ckpt = 1;
            }
            expected_counter++;
            offset = next;
        }

        if (!have_head_hash_at_ckpt) {
            /* (d) chain ends before the checkpoint's last_counter: TRUNCATED. */
            result = 0; why = "TRUNCATED: chain ends before checkpoint's last_counter";
            goto done;
        }
        if (memcmp(head_hash_at_ckpt, ckpt->head_hash, HL_HASH_SIZE) != 0) {
            result = 0; why = "checkpoint head_hash mismatch";
            goto done;
        }
    }

done:
    if (reason && reason_cap) {
        size_t l = strlen(why);
        if (l >= reason_cap) l = reason_cap - 1;
        memcpy(reason, why, l);
        reason[l] = '\0';
    }
    return result;
}

int hl_verify_chain_ckpt(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                          const hl_checkpoint_t *ckpt) {
    return hl_verify_chain_ckpt_detail(buf, n, pubkey, ckpt, NULL, 0);
}

/* Host-default millisecond clock; overridable by re-linking a different hl_now_ms in a
 * firmware build (glue layer would supply DS3231 time, 10 §6). Kept in this file (rather
 * than requiring every caller to define it) so the library is usable standalone, but any
 * production integration should override it. */
#include <time.h>
#include <sys/time.h>
uint64_t hl_now_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000ull + (uint64_t)(tv.tv_usec / 1000);
}

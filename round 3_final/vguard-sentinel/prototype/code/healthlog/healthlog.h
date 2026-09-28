/* healthlog.h — signed, append-only, hash-chained health log. C99.
 *
 * Implements the record format in healthlog/format.md and the API frozen in
 * CONTRACTS.md §6:
 *   int  hl_append(hl_t*, uint16_t type, const uint8_t* payload, size_t n);
 *   int  hl_verify_chain(const uint8_t* buf, size_t n, const uint8_t pubkey[64]);
 *
 * Design target (09-Security-OTA-and-Health-Log.md §4): production signing happens inside
 * an ATECC608 secure element whose private key never leaves it. This library never holds or
 * touches a private key — hl_append hashes the record and calls a caller-supplied
 * hl_sign_cb, which on this host prototype wraps an OpenSSL software key
 * (test_healthlog_host.c) and on the target MCU would talk to the ATECC608 over I2C. No
 * change to this file is needed to move from one signer to the other.
 *
 * Static allocation only: the log buffer is caller-owned (e.g. a static array or a memory-
 * mapped flash region); hl_t itself holds no heap pointers and this file never calls
 * malloc/free — matches the "no ESP-IDF dependency in algorithm modules" / MCU-portability
 * requirement in CONTRACTS.md §0.
 */
#ifndef HEALTHLOG_H
#define HEALTHLOG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- format constants (see format.md) --------------------------------------------- */

#define HL_HEADER_SIZE 16u   /* counter(4) + ts_ms(8) + type(2) + len(2) */
#define HL_HASH_SIZE   32u
#define HL_SIG_SIZE    64u
#define HL_PUBKEY_SIZE 64u
/* Fixed overhead per record beyond the payload: header + prev_hash + sig. */
#define HL_RECORD_OVERHEAD (HL_HEADER_SIZE + HL_HASH_SIZE + HL_SIG_SIZE) /* 112 */

/* ---- event type enum (format.md §6) — stable, never renumber ---------------------- */

enum {
    HL_EVT_FULL_CHARGE      = 0,
    HL_EVT_CAPACITY_SAMPLE   = 1,
    HL_EVT_GRADE_CHANGE      = 2,
    HL_EVT_ANOMALY           = 3,
    HL_EVT_OVER_TEMP         = 4,
    HL_EVT_DEEP_DISCHARGE    = 5,
    HL_EVT_PQ_EVENT          = 6,
    HL_EVT_CHARGER_SETPOINT  = 7,
    HL_EVT_USER_OVERRIDE     = 8,
    HL_EVT_FW_VERSION        = 9,
    HL_EVT_MODEL_VERSION     = 10,
};

/* ---- error codes returned by hl_append / hl_init / hl_resume ---------------------- */

#define HL_OK                 0
#define HL_ERR_NOMEM         -1   /* record would not fit in the remaining buffer */
#define HL_ERR_PAYLOAD_TOO_BIG -2 /* payload > 0xFFFF bytes (u16 len field) */
#define HL_ERR_SIGN_FAILED   -3   /* sign_cb returned nonzero */
#define HL_ERR_BAD_ARGS      -4
#define HL_ERR_CORRUPT       -5   /* hl_resume: existing buffer content is not a valid chain */

/* ---- signer callback ---------------------------------------------------------------
 * Must produce a raw r||s (64-byte) ECDSA-P256 signature over hash32 into sig64.
 * Returns 0 on success, nonzero on failure (hl_append then fails with HL_ERR_SIGN_FAILED
 * and does NOT advance the log state — no half-written record is left appended).
 */
typedef int (*hl_sign_cb)(const uint8_t hash32[HL_HASH_SIZE], uint8_t sig64[HL_SIG_SIZE], void *ctx);

/* ---- log handle ---------------------------------------------------------------------
 * Caller owns `buf` (static array or similar); hl_t only tracks bookkeeping over it.
 */
typedef struct {
    uint8_t     *buf;        /* caller-owned backing storage */
    size_t       cap;        /* capacity of buf, bytes */
    size_t       len;        /* bytes used in buf so far (== end of last record) */
    uint32_t     next_counter;
    uint8_t      last_hash[HL_HASH_SIZE]; /* hash of the most recently appended record;
                                              all-zero before the first append (genesis) */
    hl_sign_cb   sign_cb;
    void        *sign_ctx;
} hl_t;

/* Start a fresh, empty log over `buf` (capacity `cap`). */
int hl_init(hl_t *hl, uint8_t *buf, size_t cap, hl_sign_cb sign_cb, void *sign_ctx);

/* Resume an existing log already occupying the first `existing_len` bytes of `buf` (total
 * capacity `cap`). The existing bytes are walked and structurally + hash-chain validated
 * (NOT signature-validated — no pubkey is available to a bare writer state; pass one via
 * hl_resume_verified if available) before trusting them. Returns HL_ERR_CORRUPT if the
 * existing bytes are not a well-formed chain (gap, bad linkage, truncation). */
int hl_resume(hl_t *hl, uint8_t *buf, size_t existing_len, size_t cap,
              hl_sign_cb sign_cb, void *sign_ctx);

/* Like hl_resume, but also verifies every signature against pubkey (raw 64B) before
 * trusting the existing chain — stronger than hl_resume, at the cost of requiring the
 * caller to have the public key on hand (which it always does; the public key is not
 * secret). Prefer this over hl_resume when a pubkey is available. */
int hl_resume_verified(hl_t *hl, uint8_t *buf, size_t existing_len, size_t cap,
                        hl_sign_cb sign_cb, void *sign_ctx, const uint8_t pubkey[HL_PUBKEY_SIZE]);

/* Append one event record: hashes header||payload||prev_hash, signs the hash via
 * sign_cb, and appends the full record to hl->buf. Returns HL_OK (0) or a negative
 * HL_ERR_* code; on any failure hl->len/next_counter/last_hash are unchanged. */
int hl_append(hl_t *hl, uint16_t type, const uint8_t *payload, size_t n);

/* Bytes currently used in hl->buf (== hl->len). */
size_t hl_length(const hl_t *hl);

/* Verify a serialized chain (CONTRACTS.md §6 signature). buf/n need not come from an hl_t
 * at all — this is a pure function over bytes, matching how a verifier only ever has the
 * uploaded claim bundle and the registered public key, never the writer's live state.
 *
 * Returns 1 if the entire chain verifies (every record's counter is contiguous from 0,
 * every prev_hash links correctly, every signature checks out against pubkey), 0
 * otherwise. This is intentionally the coarse pass/fail the CONTRACTS signature commits
 * to; hl_verify_chain_detail below gives the same richer report as healthlog.py's
 * verify_chain for debugging/tests. */
int hl_verify_chain(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE]);

/* Richer verification, mirroring healthlog.py's verify_chain() return tuple. Any of the
 * output pointers may be NULL if the caller doesn't need that field. Returns the same 0/1
 * as hl_verify_chain. `reason` must point to a caller-provided buffer of at least
 * `reason_cap` bytes; the message is NUL-terminated (truncated if necessary). */
int hl_verify_chain_detail(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                            size_t *n_records_ok, int64_t *first_bad_index,
                            char *reason, size_t reason_cap);

/* ---- signed checkpoints (format.md §8) -----------------------------------------------
 * A checkpoint is a small, independently-signed attestation of "the chain's head is at
 * counter `last_counter`, whose own hash is `head_hash`, as of `ts_ms`" — see format.md §8
 * for the wire layout and README.md's threat table for the intended upload-cadence use
 * (uploaded with every telemetry batch and on every app sync, 08 §A3 / 09 §4). It does NOT
 * make the chain itself any bigger; it's a separate, tiny (108-byte) signed object that a
 * verifier who is not present for every record can still pin the chain's growth against
 * later, to catch a clean truncation of the *tail* — see README "Honest limits".
 */
#define HL_CHECKPOINT_SIZE (4u + 8u + HL_HASH_SIZE + HL_SIG_SIZE) /* 108 */

typedef struct {
    uint32_t last_counter;                 /* counter of the newest record covered */
    uint64_t ts_ms;                        /* when the checkpoint was produced */
    uint8_t  head_hash[HL_HASH_SIZE];      /* running hash of the record at last_counter */
    uint8_t  sig[HL_SIG_SIZE];             /* ECDSA-P256 raw r||s over
                                             * SHA-256(last_counter||ts_ms||head_hash) */
} hl_checkpoint_t;

/* Produce a checkpoint over hl's current head (the most recently appended record). Fails
 * with HL_ERR_BAD_ARGS if hl has no records yet (next_counter == 0) — there is nothing to
 * checkpoint. Signs through the same hl->sign_cb as hl_append (never touches a private key
 * directly), so on any failure returns HL_ERR_SIGN_FAILED and *out is left unwritten. */
int hl_checkpoint(hl_t *hl, hl_checkpoint_t *out);

/* Serialize/parse the fixed HL_CHECKPOINT_SIZE-byte wire form (format.md §8). Parse returns
 * HL_ERR_BAD_ARGS if `n` is smaller than HL_CHECKPOINT_SIZE. */
void hl_checkpoint_serialize(const hl_checkpoint_t *ckpt, uint8_t out[HL_CHECKPOINT_SIZE]);
int hl_checkpoint_parse(const uint8_t *buf, size_t n, hl_checkpoint_t *out);

/* Verify a serialized chain against both `pubkey` and a previously-obtained `ckpt`:
 *   (a) the checkpoint's own signature must verify against pubkey;
 *   (b) the chain must contain a record at counter == ckpt->last_counter whose own
 *       (recomputed) hash equals ckpt->head_hash;
 *   (c) every record present must itself verify (tamper/gap/reorder/replay checks, same as
 *       hl_verify_chain);
 *   (d) a chain that ends before ckpt->last_counter is reported as truncated — this is the
 *       one case hl_verify_chain alone cannot catch without external knowledge (README
 *       "Honest limits" / format.md §8). The chain MAY be longer than ckpt->last_counter
 *       (newer records appended since the checkpoint was taken are allowed).
 * Returns 1 if all of the above hold, 0 otherwise. */
int hl_verify_chain_ckpt(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                          const hl_checkpoint_t *ckpt);

/* Same as hl_verify_chain_ckpt but also reports a human-readable reason (mirrors
 * hl_verify_chain_detail); a truncation failure's reason always contains the substring
 * "TRUNCATED". `reason`/`reason_cap` behave as in hl_verify_chain_detail. */
int hl_verify_chain_ckpt_detail(const uint8_t *buf, size_t n, const uint8_t pubkey[HL_PUBKEY_SIZE],
                                 const hl_checkpoint_t *ckpt, char *reason, size_t reason_cap);

#ifdef __cplusplus
}
#endif

#endif /* HEALTHLOG_H */

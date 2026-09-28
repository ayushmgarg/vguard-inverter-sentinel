/* Minimal self-contained SHA-256 (public-domain style implementation), C99, no dependencies.
 *
 * Used by healthlog.c whenever libcrypto/OpenSSL is not available at build time (see
 * Makefile's HL_USE_OPENSSL auto-detection and healthlog/README.md). Kept deliberately small
 * and dependency-free because it is also the realistic path for the actual ESP32-S3 firmware
 * build (09 doc: OpenSSL is not what runs there; a hand-rolled or mbedTLS SHA-256 is), even
 * though CONTRACTS.md scopes ESP-IDF glue itself out of this algorithm module.
 */
#ifndef HL_SHA256_H
#define HL_SHA256_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t state[8];
    uint64_t bitlen;
    uint8_t  buf[64];
    size_t   buf_len;
} hl_sha256_ctx_t;

void hl_sha256_init(hl_sha256_ctx_t *ctx);
void hl_sha256_update(hl_sha256_ctx_t *ctx, const uint8_t *data, size_t len);
void hl_sha256_final(hl_sha256_ctx_t *ctx, uint8_t out[32]);

/* Convenience one-shot. */
void hl_sha256(const uint8_t *data, size_t len, uint8_t out[32]);

#endif /* HL_SHA256_H */

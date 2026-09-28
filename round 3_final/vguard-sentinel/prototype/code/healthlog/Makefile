# healthlog — host build. C99, gcc. See README.md and CONTRACTS.md §0/§6.
#
# Auto-detects libcrypto (OpenSSL) via pkg-config. If present: SHA-256 and ECDSA-P256
# verify both use libcrypto (HL_USE_OPENSSL). If absent: SHA-256 falls back to the
# self-contained sha256.c, and ECDSA verify is unavailable in hl_verify_chain (hash-chain-
# only check; documented limit, see README). Signing is ALWAYS via the hl_sign_cb
# callback regardless of backend — this library never holds a private key.

CC      ?= gcc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -g
LDFLAGS ?=

HAVE_OPENSSL := $(shell pkg-config --exists libcrypto 2>/dev/null && echo 1 || echo 0)

ifeq ($(HAVE_OPENSSL),1)
# -Wno-deprecated-declarations: OpenSSL 3.0 deprecates the low-level EC_KEY/ECDSA_SIG API
# in favour of EVP_PKEY, but EC_KEY is still the correct tool for extracting/injecting raw
# (r, s) components for our fixed 64-byte wire signature — EVP_PKEY only speaks DER. Fully
# functional, just steers callers toward EVP_PKEY for new code that doesn't need raw r||s.
CFLAGS  += -DHL_USE_OPENSSL -Wno-deprecated-declarations $(shell pkg-config --cflags libcrypto)
LDFLAGS += $(shell pkg-config --libs libcrypto)
SRCS    := healthlog.c
else
CFLAGS  += -DHL_NO_OPENSSL
SRCS    := healthlog.c sha256.c
endif

OBJS := $(SRCS:.c=.o)

.PHONY: all test clean backend
all: test_healthlog_host

backend:
	@echo "HAVE_OPENSSL=$(HAVE_OPENSSL)"

%.o: %.c healthlog.h sha256.h
	$(CC) $(CFLAGS) -c $< -o $@

test_healthlog_host: test_healthlog_host.o $(OBJS)
	$(CC) $(CFLAGS) -o $@ test_healthlog_host.o $(OBJS) $(LDFLAGS)

test: test_healthlog_host
	./test_healthlog_host

clean:
	rm -f *.o test_healthlog_host chain_from_c.bin pubkey_from_c.bin checkpoint_from_c.bin

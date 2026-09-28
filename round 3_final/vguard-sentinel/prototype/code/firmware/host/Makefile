# firmware/host/Makefile -- host build of sentinel_host_sim (the deliverable
# actually built and run in this environment; ESP-IDF is not installed here).
#
# `make host` (this Makefile's default target, also aliased from a shell one
# level up if invoked as `make -C firmware/host`) links:
#   - the portable engine (../main/sentinel_core.c, cycle_feat.c, grade.c, state_json.c)
#   - the hand-written int8 CNN (../components/sentinel_int8/sentinel_int8.c)
#   - the REAL algorithm modules by path (ekf.c, autopilot.c, healthlog.c[, sha256.c])
# against this file (sentinel_host_sim.c), exactly mirroring healthlog/Makefile's
# OpenSSL auto-detection (see that file's comment block).

CC      ?= gcc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -g
LDFLAGS ?= -lm

ROOT       := ../..
EKF_DIR    := $(ROOT)/ekf
AP_DIR     := $(ROOT)/autopilot
HL_DIR     := $(ROOT)/healthlog
MODEL_DIR  := $(ROOT)/model/artifacts_sim
MAIN_DIR   := ../main
SINT8_DIR  := ../components/sentinel_int8

INCLUDES := -I$(EKF_DIR) -I$(AP_DIR) -I$(HL_DIR) -I$(MODEL_DIR) -I$(MAIN_DIR) -I$(SINT8_DIR)/include

HAVE_OPENSSL := $(shell pkg-config --exists libcrypto 2>/dev/null && echo 1 || echo 0)
ifneq ($(HAVE_OPENSSL),1)
$(error firmware/host requires libcrypto (OpenSSL) for the health-log signer -- \
  see healthlog/Makefile's comment block; install libssl-dev / openssl-devel)
endif

CFLAGS  += -DHL_USE_OPENSSL -Wno-deprecated-declarations $(shell pkg-config --cflags libcrypto)
LDFLAGS += $(shell pkg-config --libs libcrypto)

SRCS := \
    sentinel_host_sim.c \
    $(MAIN_DIR)/sentinel_core.c \
    $(MAIN_DIR)/cycle_feat.c \
    $(MAIN_DIR)/grade.c \
    $(MAIN_DIR)/state_json.c \
    $(SINT8_DIR)/sentinel_int8.c \
    $(EKF_DIR)/ekf.c \
    $(AP_DIR)/autopilot.c \
    $(HL_DIR)/healthlog.c

OBJS := $(SRCS:.c=.o)
BIN  := sentinel_host_sim

.PHONY: all host test clean
all: $(BIN)
host: $(BIN)

%.o: %.c
	$(CC) $(CFLAGS) $(INCLUDES) -c $< -o $@

$(BIN): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDFLAGS)

# Short smoke run: 20000 rows (~5.5h simulated) of the first sim battery.
test: $(BIN)
	./$(BIN) --csv $(ROOT)/data/sim_1hz/battery_000.csv --manifest $(ROOT)/data/sim_1hz/manifest.csv \
		--out state.json --max-rows 20000

clean:
	rm -f $(OBJS) $(BIN) state.json state.json.tmp

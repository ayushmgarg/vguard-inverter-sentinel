# Makefile for the autopilot C99 module (host build only -- ESP-IDF glue
# lives in firmware/, per CONTRACTS.md Sec.0/3).

CC ?= gcc
CFLAGS ?= -std=c99 -Wall -Wextra -O2 -g
LDLIBS := -lm

.PHONY: all test clean

all: test_autopilot_host

test_autopilot_host: test_autopilot_host.c autopilot.c autopilot.h
	$(CC) $(CFLAGS) -o $@ test_autopilot_host.c autopilot.c $(LDLIBS)

test: test_autopilot_host
	./test_autopilot_host

clean:
	rm -f test_autopilot_host *.o

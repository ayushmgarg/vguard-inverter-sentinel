# ekf/Makefile -- host build for the C EKF port (CONTRACTS.md: C99, gcc).
CC ?= gcc
CFLAGS ?= -std=c99 -O2 -Wall -Wextra -lm
LDLIBS = -lm

.PHONY: all clean test

all: ekf_test_host

ekf_test_host: ekf.c ekf.h test_ekf_host.c
	$(CC) $(CFLAGS) -o $@ ekf.c test_ekf_host.c $(LDLIBS)

# Usage: make test IN=sim_ekf_data.csv OUT=ekf_c_trace.csv
test: ekf_test_host
	./ekf_test_host $(IN) $(OUT)

clean:
	rm -f ekf_test_host *.o

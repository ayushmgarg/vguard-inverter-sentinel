# Makefile for the charger C99 frame codec (host build only -- ESP-IDF glue
# lives in firmware/, per CONTRACTS.md Sec.0/3).

CC ?= gcc
CFLAGS ?= -std=c99 -Wall -Wextra -O2 -g
LDLIBS := -lm

.PHONY: all test clean

all: test_frames_host

test_frames_host: test_frames_host.c frames.c frames.h
	$(CC) $(CFLAGS) -o $@ test_frames_host.c frames.c $(LDLIBS)

test: test_frames_host
	./test_frames_host
	./test_frames_host --vectors parity_vectors.txt

clean:
	rm -f test_frames_host *.o

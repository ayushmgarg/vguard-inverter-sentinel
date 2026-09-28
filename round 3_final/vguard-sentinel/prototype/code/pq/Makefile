CC = gcc
CFLAGS = -std=c99 -O2 -Wall -Wextra
LDLIBS = -lm

.PHONY: all test clean

all: pq_main test_pq_host

pq_main: pq_main.c pq.c pq.h
	$(CC) $(CFLAGS) -o pq_main pq_main.c pq.c $(LDLIBS)

test_pq_host: test_pq_host.c pq.c pq.h
	$(CC) $(CFLAGS) -o test_pq_host test_pq_host.c pq.c $(LDLIBS)

test: test_pq_host
	./test_pq_host

clean:
	rm -f pq_main test_pq_host *.o

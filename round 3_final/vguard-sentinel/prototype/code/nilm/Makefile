CC = gcc
CFLAGS = -std=c99 -O2 -Wall -Wextra
LDLIBS = -lm

.PHONY: all test clean

all: event_detector_main test_event_detector_host test_pzem_parser_host

event_detector_main: event_detector_main.c event_detector.c event_detector.h
	$(CC) $(CFLAGS) -o event_detector_main event_detector_main.c event_detector.c $(LDLIBS)

test_event_detector_host: test_event_detector_host.c event_detector.c event_detector.h
	$(CC) $(CFLAGS) -o test_event_detector_host test_event_detector_host.c event_detector.c $(LDLIBS)

test_pzem_parser_host: test_pzem_parser_host.c pzem_parser.c pzem_parser.h
	$(CC) $(CFLAGS) -o test_pzem_parser_host test_pzem_parser_host.c pzem_parser.c $(LDLIBS)

test: test_event_detector_host test_pzem_parser_host
	./test_event_detector_host
	./test_pzem_parser_host

clean:
	rm -f event_detector_main test_event_detector_host test_pzem_parser_host *.o

/* firmware/main/pzem_uart.h -- UART Modbus polling for PZEM-004T v3, using
 * nilm/pzem_parser.h (already CRC-verified, host-tested) to decode the response
 * frame. ESP-IDF specific (driver/uart.h), NEVER BUILT here.
 *
 * Used on Tier-0 installs without the ATM90E32AS AFE (03-Parts-Placement §4:
 * "AFE or CT missing: Coach and PQ disabled, everything else runs" -- PZEM gives a
 * coarser 1 Hz P/V/I/PF/f stream that still feeds nilm/event_detector.h's Tier-0
 * path, design 06's honesty note that r_pk/h are always NAN on this path).
 */
#ifndef SENTINEL_PZEM_UART_H
#define SENTINEL_PZEM_UART_H

#include <stdbool.h>
#include <stdint.h>

#include "pzem_parser.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int     uart_port;     /* uart_port_t */
    uint8_t slave_addr;
} pzem_uart_t;

int pzem_uart_init(pzem_uart_t *dev, int uart_port, int tx_gpio, int rx_gpio, uint8_t slave_addr);

/* Sends the "read input registers 0x0000-0x0009" request, waits for the
 * PZEM_FRAME_LEN-byte response (100 ms timeout), and parses it with
 * pzem_parse_frame(). Returns 0 on success; negative on UART timeout/error or a
 * pzem_parse_frame() failure (CRC mismatch etc, propagated as -10 + the parser's
 * own negative code so the caller can distinguish "no response" from "garbled
 * response" -- design 04 §6 sensor-fault handling wants that distinction). */
int pzem_uart_read(pzem_uart_t *dev, pzem_reading_t *out);

#ifdef __cplusplus
}
#endif

#endif /* SENTINEL_PZEM_UART_H */

/* firmware/main/pzem_uart.c -- see pzem_uart.h. ESP-IDF specific, NEVER BUILT here. */
#include "pzem_uart.h"

#include <string.h>

#ifdef ESP_PLATFORM
#include "driver/uart.h"
#include "esp_log.h"
static const char *TAG = "pzem_uart";
#endif

#define PZEM_REQUEST_LEN 8
#define PZEM_UART_BAUD 9600
#define PZEM_READ_TIMEOUT_MS 100

int pzem_uart_init(pzem_uart_t *dev, int uart_port, int tx_gpio, int rx_gpio, uint8_t slave_addr) {
    if (!dev) return -1;
    memset(dev, 0, sizeof(*dev));
    dev->uart_port = uart_port;
    dev->slave_addr = slave_addr;

#ifdef ESP_PLATFORM
    uart_config_t cfg = {
        .baud_rate = PZEM_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    if (uart_param_config((uart_port_t)uart_port, &cfg) != ESP_OK) return -2;
    if (uart_set_pin((uart_port_t)uart_port, tx_gpio, rx_gpio, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK) return -2;
    if (uart_driver_install((uart_port_t)uart_port, 256, 256, 0, NULL, 0) != ESP_OK) return -2;
    return 0;
#else
    (void)tx_gpio; (void)rx_gpio;
    return -2; /* host build never calls this */
#endif
}

int pzem_uart_read(pzem_uart_t *dev, pzem_reading_t *out) {
    if (!dev || !out) return -1;

    uint8_t req[PZEM_REQUEST_LEN] = {
        dev->slave_addr, PZEM_FUNC_READ, 0x00, 0x00, 0x00, 0x0A, 0x00, 0x00,
    };
    uint16_t crc = pzem_crc16(req, 6);
    req[6] = (uint8_t)(crc & 0xFF);
    req[7] = (uint8_t)(crc >> 8);

#ifdef ESP_PLATFORM
    uart_flush_input((uart_port_t)dev->uart_port);
    int written = uart_write_bytes((uart_port_t)dev->uart_port, (const char *)req, sizeof(req));
    if (written != (int)sizeof(req)) { ESP_LOGE(TAG, "uart_write_bytes short write"); return -2; }

    uint8_t resp[PZEM_FRAME_LEN];
    int n = uart_read_bytes((uart_port_t)dev->uart_port, resp, sizeof(resp),
                             pdMS_TO_TICKS(PZEM_READ_TIMEOUT_MS));
    if (n != PZEM_FRAME_LEN) { ESP_LOGW(TAG, "pzem read timeout/short (%d bytes)", n); return -3; }

    int rc = pzem_parse_frame(resp, (size_t)n, out);
    if (rc != 0) { ESP_LOGW(TAG, "pzem_parse_frame failed: %d", rc); return -10 + rc; }
    return 0;
#else
    (void)crc;
    return -2;
#endif
}

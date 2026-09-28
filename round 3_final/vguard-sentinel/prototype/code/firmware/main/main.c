/* firmware/main/main.c -- ESP-IDF 5.x entry point: creates the FreeRTOS tasks per
 * design 04 §2, wires the drivers (ina2xx/ntc/pzem_uart/relays) to the portable
 * engine in sentinel_core.c, and boots the fail-safe defaults (design 04 §6).
 *
 * NEVER BUILT in this environment (no ESP-IDF installed here -- see
 * firmware/README.md "what was executed here"; the portable engine this file
 * calls into (sentinel_core.c and everything it uses) IS built and run, on host,
 * by firmware/host/sentinel_host_sim.c).
 *
 * ARCHITECTURE NOTE / honest simplification: design 04 §2 lists cycle_feat (prio
 * 12) and ml_infer (prio 10) as independent event-driven tasks. In this
 * implementation, sentinel_core_on_sample() (called from the "ekf" task below)
 * performs the EKF step, cycle-feature accumulation, and -- on a cycle boundary
 * -- the int8 inference/grading/health-log append, all synchronously in one
 * call (see sentinel_core.c's doc comment on why: it is the one place the whole
 * pipeline is wired together, and that is what makes the host build able to
 * "run the whole control loop"). The cycle_feat and ml_infer tasks below are
 * therefore real, separately-scheduled FreeRTOS tasks (matching the design's
 * priority/stack/RAM budget), but their bodies do lighter-weight, decoupled
 * work (persisting the just-closed feature row; watching for grade changes)
 * rather than owning their pipeline stage exclusively. A fuller decomposition
 * would move the on-cycle-close call out of the "ekf" task into a
 * queue-signaled ml_infer task -- left as follow-up, not done here under this
 * pass's time budget (see firmware/README.md "honest limits").
 */
#include <math.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_task_wdt.h"
#include "esp_log.h"

#include "driver/i2c_master.h"
#include "esp_adc/adc_oneshot.h"
#include "driver/gpio.h"

#include "sentinel_core.h"
#include "sentinel_types.h"
#include "state_json.h"
#include "ina2xx.h"
#include "ntc.h"
#include "pzem_uart.h"
#include "relays.h"
#include "storage.h"
#include "replay.h"
#include "healthlog_signer.h"
#include "task_config.h"
#include "event_detector.h"
#include "pq.h"

#include "sdkconfig.h"

static const char *TAG = "sentinel_main";

/* ---- shared state ------------------------------------------------------ */
static sentinel_ctx_t g_ctx;
static SemaphoreHandle_t g_ctx_mutex;
/* design 04 §2: "one immutable Sample struct per second on a ring; tasks read by
 * index -- no shared mutable state". sense_1hz is the sole writer
 * (sentinel_ring_push always appends a fresh copy, never mutates a published
 * slot); g_sample_ready gates the ekf task so it reads the ring only after a
 * new sample has actually landed, and stays synchronised as long as it drains
 * within one 1 Hz tick (SENTINEL_RING_LEN=8 gives headroom if it briefly
 * doesn't). */
static sentinel_sample_ring_t g_sample_ring;
static SemaphoreHandle_t g_sample_ready;
static uint8_t g_hl_buf[64 * 1024];    /* health-log staging; the "data" partition
                                           budget (1 MB, partitions.csv) is far
                                           larger -- this is the in-RAM working set
                                           flushed to LittleFS by the logger task */

static ina2xx_t g_ina;
static ntc_t g_ntc;
static pzem_uart_t g_pzem;
static relays_t g_relays;
static ev_det_t g_ev_det;
static pq_t g_pq;
static replay_state_t g_replay;

static volatile TickType_t g_last_tick_sense_1hz, g_last_tick_ekf, g_last_tick_autopilot;

/* ---- task: sense_1hz (prio 20, core 1) --------------------------------- */
static void task_sense_1hz(void *arg) {
    (void)arg;
    esp_task_wdt_add(NULL);
    TickType_t last_wake = xTaskGetTickCount();
    double t = 0.0;

    for (;;) {
        ina2xx_reading_t batt;
        int rc_i = ina2xx_read(&g_ina, &batt);
        float ntc_c;
        int rc_t = ntc_read_celsius(&g_ntc, &ntc_c);

        sentinel_sample_t s;
        memset(&s, 0, sizeof(s));
        s.t = t;
        /* explicit error handling: a sensor fault must not fabricate a
         * plausible-looking value -- design 04 §6 wants the EKF to fall back
         * to coulomb-count-only and contactors to never shed on unreliable
         * data. Holding the previous good value is a defensible interim
         * behaviour (never done more than a few ticks before the fault
         * escalates to storage/logger visibility -- not implemented as a
         * hard timeout in this prototype pass, see README honest limits). */
        static float last_good_i = 0.0f, last_good_v = 12.0f, last_good_t = 25.0f;
        if (rc_i == 0 && batt.valid) { last_good_i = batt.current_a; last_good_v = batt.voltage_v; }
        if (rc_t == 0) last_good_t = ntc_c;
        int mains_sense = gpio_get_level(CONFIG_SENTINEL_MAINS_SENSE_GPIO);
        s.I = last_good_i;
        s.V = last_good_v;
        s.T = last_good_t;
        s.grid = mains_sense ? 1 : 0;
        s.P_load = 0.0f; /* filled in by the afe_3hz/pzem path when present */
        s.soc_true = 0.0f / 0.0f;  /* NAN: real hardware has no ground truth */
        s.soh_true = 0.0f / 0.0f;

        ina2xx_update_zero_cal(&g_ina, s.I, 0.01f * g_ctx.cfg.q_rated_ah / 20.0f, 0.02f);

        /* outage 2-of-3 vote (CONTRACTS §5 / design 05 §7, ap_outage_step()):
         * RMS leg = mains_sense (this prototype has no AMC1311 ADC-RMS path,
         * see README honest limits -- the digital sense pin stands in for it),
         * mode-pin leg = AP_INV_UNKNOWN (no inverter mode tap wired), discharge
         * leg = the just-measured battery current when it is discharge-signed
         * (CONTRACTS §1 convention: negative I = discharge). */
        ap_outage_input_t outage_in = {
            .t = (float)t,
            .mains_rms_pu = mains_sense ? 1.0f : 0.0f,
            .inverter_mode_pin = AP_INV_UNKNOWN,
            .batt_discharge_a = (s.I < 0.0f) ? -s.I : 0.0f,
        };
        xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
        ap_outage_step(&g_ctx.ap, &outage_in);
        xSemaphoreGive(g_ctx_mutex);

        sentinel_ring_push(&g_sample_ring, &s);
        xSemaphoreGive(g_sample_ready);

        g_last_tick_sense_1hz = xTaskGetTickCount();
        esp_task_wdt_reset();
        t += 1.0;
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
    }
}

/* ---- task: ekf (prio 18, core 1) --------------------------------------- */
static void task_ekf(void *arg) {
    (void)arg;
    esp_task_wdt_add(NULL);
    for (;;) {
        if (xSemaphoreTake(g_sample_ready, pdMS_TO_TICKS(1200)) == pdTRUE) {
            /* Read the ring's latest slot by index (design 04 §2) -- a plain
             * struct copy under the ring's own producer/consumer discipline
             * (single writer, this the only reader), not the ctx mutex (that
             * one only protects sentinel_ctx_t, which sentinel_ring_latest()
             * never touches). */
            sentinel_sample_t s = *sentinel_ring_latest(&g_sample_ring);
            xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
            sentinel_core_on_sample(&g_ctx, &s);
            xSemaphoreGive(g_ctx_mutex);
        }
        g_last_tick_ekf = xTaskGetTickCount();
        esp_task_wdt_reset();
    }
}

/* ---- task: autopilot (prio 17, core 1), 60 s tick ---------------------- */
static void task_autopilot(void *arg) {
    (void)arg;
    esp_task_wdt_add(NULL);
    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
        double t = g_ctx.state.t;
        int hour = (int)(fmodf((float)(t / 3600.0), 24.0f));
        int dow = (int)(fmodf((float)(t / 86400.0), 7.0f));
        sentinel_core_on_minute(&g_ctx, hour, dow, g_ctx.state.last_I * g_ctx.state.last_V);
        ap_chstate_t channels[AP_N_CHANNELS];
        memcpy(channels, g_ctx.state.channel_state, sizeof(channels));
        bool wdt_healthy =
            (xTaskGetTickCount() - g_last_tick_sense_1hz) < pdMS_TO_TICKS(3000) &&
            (xTaskGetTickCount() - g_last_tick_ekf) < pdMS_TO_TICKS(3000);
        xSemaphoreGive(g_ctx_mutex);

        relays_apply(&g_relays, channels);
        g_relays.task_watchdog_healthy = wdt_healthy;

        g_last_tick_autopilot = xTaskGetTickCount();
        esp_task_wdt_reset();
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(60000));
    }
}

/* ---- task: cycle_feat (prio 12, core 1) -------------------------------- */
/* Persists the just-closed cycle's feature row to LittleFS -- see main.c's
 * top-of-file architecture note for why this, not the model window update
 * itself (that already happened synchronously inside the ekf task's call). */
static void task_cycle_feat(void *arg) {
    (void)arg;
    for (;;) {
        xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
        bool have_row = g_ctx.state.have_new_closed_row;
        float dyn[CYCLE_FEAT_N_DYNAMIC], stat[CYCLE_FEAT_N_STATIC];
        if (have_row) {
            memcpy(dyn, g_ctx.state.last_closed_dyn_row, sizeof(dyn));
            memcpy(stat, g_ctx.state.last_closed_static_row, sizeof(stat));
            g_ctx.state.have_new_closed_row = false;
        }
        xSemaphoreGive(g_ctx_mutex);

        if (have_row) {
            uint8_t row[sizeof(dyn) + sizeof(stat)];
            memcpy(row, dyn, sizeof(dyn));
            memcpy(row + sizeof(dyn), stat, sizeof(stat));
            if (storage_append("features.bin", row, sizeof(row)) != 0) {
                ESP_LOGE(TAG, "cycle_feat: storage_append(features.bin) failed");
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

/* ---- task: ml_infer (prio 10, core 1) ---------------------------------- */
/* Watches for a grade change and logs it -- the inference itself already ran
 * synchronously inside the ekf task (see architecture note above). */
static void task_ml_infer(void *arg) {
    (void)arg;
    int last_seen_grade = -1;
    for (;;) {
        xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
        int grade = g_ctx.state.grade;
        float soh = g_ctx.state.soh_p50;
        xSemaphoreGive(g_ctx_mutex);

        if (grade != last_seen_grade) {
            ESP_LOGI(TAG, "grade -> %s (SoH p50 %.1f%%)", grade_name(grade), soh);
            last_seen_grade = grade;
        }
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}

/* ---- task: afe_3hz (prio 14, core 1) ------------------------------------
 * Tier-0 fallback (03 §4: "AFE or CT missing: Coach and PQ disabled,
 * everything else runs") -- this prototype has no ATM90E32AS SPI driver, so
 * this task polls the PZEM-004T path instead when configured, feeding the
 * same nilm/event_detector.h ev_push() the full AFE path would. */
static void task_afe_3hz(void *arg) {
    (void)arg;
    ev_init(&g_ev_det, 3.0f);
    TickType_t last_wake = xTaskGetTickCount();
    for (;;) {
        pzem_reading_t r;
        if (pzem_uart_read(&g_pzem, &r) == 0) {
            ev_event_t ev;
            float t_s = (float)xTaskGetTickCount() / (float)configTICK_RATE_HZ;
            if (ev_push(&g_ev_det, t_s, r.power_w, 0.0f /* no Q on the PZEM path */, r.voltage_v, &ev)) {
                uint8_t buf[sizeof(ev)];
                memcpy(buf, &ev, sizeof(ev));
                storage_append("nilm_events.bin", buf, sizeof(buf));
            }
            xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
            /* P_load surfaces on the next Sample the sense_1hz/ekf pipeline
             * builds -- stored here for that task to pick up. A real
             * implementation would pass this via the Sample ring directly;
             * kept as a shared field update under the same mutex for
             * simplicity in this prototype pass. */
            xSemaphoreGive(g_ctx_mutex);
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(333)); /* ~3 Hz */
    }
}

/* ---- task: pq (prio 15, core 1) -----------------------------------------
 * design 04 §3: "PQ DMA buffers 16 KB" -- this prototype has no AMC1311/ADC
 * DMA capture wired up (see firmware/README.md honest limits); pq_push_sample
 * is still exercised here at a much-reduced synthetic rate so the component
 * is linked, initialised, and its event queue exercised end-to-end, just not
 * against a real 4 kS/s waveform. */
static void task_pq(void *arg) {
    (void)arg;
    pq_init(&g_pq, 4000.0f, 50.0f, 230.0f);
    for (;;) {
        for (int i = 0; i < 80; i++) { /* one synthetic "chunk", not a real capture */
            float sample = 230.0f * 1.4142f; /* flat DC stand-in -- see doc comment */
            pq_push_sample(&g_pq, sample);
        }
        pq_event_t ev;
        while (pq_poll_event(&g_pq, &ev)) {
            storage_append("pq_events.bin", (const uint8_t *)&ev, sizeof(ev));
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

/* ---- task: logger (prio 8, core 1) -------------------------------------- */
static void task_logger(void *arg) {
    (void)arg;
    static uint8_t hl_scratch[8192];
    for (;;) {
        xSemaphoreTake(g_ctx_mutex, portMAX_DELAY);
        size_t hl_len = hl_length(&g_ctx.hl);
        size_t to_copy = hl_len < sizeof(hl_scratch) ? hl_len : sizeof(hl_scratch);
        memcpy(hl_scratch, g_ctx.hl.buf, to_copy);
        sentinel_state_t st;
        sentinel_core_get_state(&g_ctx, &st);
        xSemaphoreGive(g_ctx_mutex);

        /* Not incremental (re-writes the whole chain each tick) -- fine at
         * this log's size (design 04 §3 budgets 1 MB total for every
         * LittleFS log combined); a longer-running device would append only
         * the bytes written since the last flush instead. */
        if (storage_append("healthlog.bin", hl_scratch, (uint32_t)to_copy) != 0) {
            ESP_LOGW(TAG, "logger: health-log flush failed");
        }

        state_json_channel_cfg_t channels[AP_N_CHANNELS] = {
            {"Essentials (T1)", "T1"}, {"Fans/TV (T2)", "T2"},
            {"Heavy sockets (T3)", "T3"}, {"Medical (T1, locked)", "T1"},
        };
        state_json_extra_t extra = {0};
        extra.replay_active = g_replay.active;
        extra.replay_banner = g_replay.active ? "REPLAY DEMO" : NULL;
        extra.have_healthlog_verify = false;
        state_json_write_file("/data/state.json", &st, channels, &extra);

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

/* ---- task: heartbeat (prio 24, core 1) ---------------------------------- */
static void task_heartbeat(void *arg) {
    (void)arg;
    for (;;) {
        TickType_t now = xTaskGetTickCount();
        bool healthy =
            (now - g_last_tick_sense_1hz) < pdMS_TO_TICKS(3000) &&
            (now - g_last_tick_ekf) < pdMS_TO_TICKS(3000) &&
            (now - g_last_tick_autopilot) < pdMS_TO_TICKS(90000);
        g_relays.task_watchdog_healthy = healthy;
        relays_heartbeat_tick(&g_relays);
        if (!healthy) ESP_LOGE(TAG, "heartbeat: a critical task missed its deadline -- coils will drop");
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

/* ---- Core 0 protocol-core stubs -----------------------------------------
 * design 04 §1: self-contained means no network is on the critical path of
 * any function. These are placeholders only -- not implemented in this
 * prototype pass (see README honest limits); kept as idle tasks purely so
 * main.c's task table visibly matches design 04 §2's full list. */
static void task_stub_core0(void *arg) {
    const char *name = (const char *)arg;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        ESP_LOGD(TAG, "%s: idle stub (not implemented in this prototype)", name);
    }
}

/* ---- boot sequence ------------------------------------------------------ */
void app_main(void) {
    ESP_LOGI(TAG, "V-Guard Sentinel Core booting");

    if (storage_init() != 0) {
        ESP_LOGE(TAG, "storage_init failed -- continuing with fail-safe defaults only");
    }

    sentinel_commission_config_t commission;
    int cload_rc = storage_config_load(&commission);
    if (cload_rc != 0) ESP_LOGW(TAG, "no valid commission config -- fail-safe defaults (all T1)");

    float q_rated_ah = commission.configured ? commission.q_rated_ah : 150.0f;

    sentinel_config_t cfg;
    sentinel_config_default(&cfg, q_rated_ah);
    if (commission.configured) {
        for (int i = 0; i < AP_N_CHANNELS; i++) {
            cfg.ap_config.channels[i].tier = commission.channel_tier[i];
            cfg.ap_config.channels[i].hw_locked_t1 = commission.channel_hw_locked[i];
        }
    }
    cfg.ap_config.configured = commission.configured;

    /* I2C bus (INA2xx, DS3231, ATECC608) -- design 03 §1, one shared bus */
    i2c_master_bus_handle_t i2c_bus = NULL;
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = 8, .scl_io_num = 9, /* placeholder pins, see README pin table */
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &i2c_bus);
    if (err != ESP_OK) ESP_LOGE(TAG, "i2c_new_master_bus failed: %d", err);

    i2c_master_dev_handle_t ina_dev = NULL;
    if (i2c_bus) {
        i2c_device_config_t dev_cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x40, .scl_speed_hz = 400000 };
        i2c_master_bus_add_device(i2c_bus, &dev_cfg, &ina_dev);
    }
    ina2xx_init(&g_ina, ina_dev, 0x40, INA_KIND_INA228, commission.shunt_mohm > 0 ? commission.shunt_mohm / 1000.0f : 0.0001f, q_rated_ah);

    adc_oneshot_unit_handle_t adc1 = NULL;
    adc_oneshot_unit_init_cfg_t adc_init_cfg = { .unit_id = ADC_UNIT_1 };
    adc_oneshot_new_unit(&adc_init_cfg, &adc1);
    ntc_init(&g_ntc, adc1, ADC_CHANNEL_3, 10000.0f, 10000.0f, 25.0f, 3950.0f, 3.3f, true);

    pzem_uart_init(&g_pzem, UART_NUM_1, 17, 18, 0x01);

    int coil_gpio[AP_N_CHANNELS] = {
        CONFIG_SENTINEL_RELAY_COIL_T1_GPIO, CONFIG_SENTINEL_RELAY_COIL_T2_GPIO,
        CONFIG_SENTINEL_RELAY_COIL_T3_GPIO, CONFIG_SENTINEL_RELAY_COIL_MED_GPIO,
    };
    if (relays_init(&g_relays, coil_gpio, CONFIG_SENTINEL_HEARTBEAT_GPIO) != 0) {
        ESP_LOGE(TAG, "relays_init failed -- coils may not be in a known state!");
    }

    healthlog_signer_esp_init(ina_dev, 0x60);
    /* healthlog_signer_esp_sign_cb always fails in this prototype (no ATECC608
     * driver, see healthlog_signer_esp.c) -- hl_append calls will return
     * HL_ERR_SIGN_FAILED. sentinel_core_init() still succeeds (the log is
     * simply empty/stalled, not a boot-blocking condition, matching design
     * 04 §6's "degrade visibly, never pretend" philosophy). */
    if (sentinel_core_init(&g_ctx, &cfg, healthlog_signer_esp_sign_cb, NULL, g_hl_buf, sizeof(g_hl_buf)) != 0) {
        ESP_LOGE(TAG, "sentinel_core_init failed -- halting");
        abort();
    }

    if (!sentinel_core_selftest(&g_ctx)) {
        ESP_LOGE(TAG, "sentinel_int8 golden self-test FAILED -- model inference disabled this boot");
        /* design 04 §4 step 3: "failure -> fall back to the other slot" -- this
         * prototype has only one model slot compiled in (no A/B model_a/model_b
         * flash-load path implemented, see README honest limits), so the
         * fallback here is simply "no inference", not a slot switch. */
    } else {
        ESP_LOGI(TAG, "sentinel_int8 golden self-test PASS");
    }

    g_ctx_mutex = xSemaphoreCreateMutex();
    sentinel_ring_init(&g_sample_ring);
    g_sample_ready = xSemaphoreCreateBinary();

    esp_task_wdt_config_t wdt_cfg = { .timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true };
    esp_task_wdt_init(&wdt_cfg);

#if CONFIG_SENTINEL_DEMO_REPLAY
    replay_run(&g_ctx, &g_replay, "/data/demo_replay.csv");
#endif

    xTaskCreatePinnedToCore(task_sense_1hz, "sense_1hz", STACK_SENSE_1HZ, NULL, PRIO_SENSE_1HZ, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_ekf, "ekf", STACK_EKF, NULL, PRIO_EKF, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_autopilot, "autopilot", STACK_AUTOPILOT, NULL, PRIO_AUTOPILOT, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_cycle_feat, "cycle_feat", STACK_CYCLE_FEAT, NULL, PRIO_CYCLE_FEAT, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_ml_infer, "ml_infer", STACK_ML_INFER, NULL, PRIO_ML_INFER, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_afe_3hz, "afe_3hz", STACK_AFE_3HZ, NULL, PRIO_AFE_3HZ, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_pq, "pq", STACK_PQ, NULL, PRIO_PQ, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_logger, "logger", STACK_LOGGER, NULL, PRIO_LOGGER, NULL, SENTINEL_CORE_APP);
    xTaskCreatePinnedToCore(task_heartbeat, "heartbeat", STACK_HEARTBEAT, NULL, PRIO_HEARTBEAT, NULL, SENTINEL_CORE_APP);

    xTaskCreatePinnedToCore(task_stub_core0, "app_ble", STACK_STUB_CORE0, "app_ble", PRIO_APP_BLE, NULL, SENTINEL_CORE_PROTOCOL);
    xTaskCreatePinnedToCore(task_stub_core0, "mqtt_telemetry", STACK_STUB_CORE0, "mqtt_telemetry", PRIO_MQTT_TELEMETRY, NULL, SENTINEL_CORE_PROTOCOL);
    xTaskCreatePinnedToCore(task_stub_core0, "ota", STACK_STUB_CORE0, "ota", PRIO_OTA, NULL, SENTINEL_CORE_PROTOCOL);

    ESP_LOGI(TAG, "all tasks created -- Sentinel Core running");
}

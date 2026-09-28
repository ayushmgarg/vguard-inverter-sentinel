# firmware/main/CMakeLists.txt
idf_component_register(
    SRCS
        "main.c"
        "sentinel_core.c"
        "cycle_feat.c"
        "grade.c"
        "state_json.c"
        "ina2xx.c"
        "ntc.c"
        "pzem_uart.c"
        "relays.c"
        "storage.c"
        "replay.c"
        "healthlog_signer_esp.c"
    INCLUDE_DIRS "."
    PRIV_INCLUDE_DIRS "../../../model/artifacts_sim"
    REQUIRES
        "ekf" "autopilot" "nilm" "pq" "healthlog" "sentinel_int8" "tflm_wrapper"
        "driver" "esp_adc" "nvs_flash" "esp_littlefs" "esp_timer"
)

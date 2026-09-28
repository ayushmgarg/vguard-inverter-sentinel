# firmware/components/healthlog -- thin ESP-IDF wrapper for code/healthlog/{healthlog,sha256}.c.
#
# Deliberately NOT defining HL_USE_OPENSSL here: on the ESP32-S3 target, signing is
# meant to happen inside the ATECC608 secure element (09-Security-OTA-and-Health-Log.md
# §4; see healthlog.h's doc comment -- "this library never holds or touches a private
# key"). There is no ATECC608 driver in this prototype (no hardware was available/
# flashed -- see firmware/README.md honest limits), so main/healthlog_signer.c's
# hl_sign_cb on the ESP32 target is a documented stub that returns HL_ERR_SIGN_FAILED
# until a real ATECC608 I2C driver is wired in. The host build (firmware/host/) instead
# defines HL_USE_OPENSSL and links libcrypto, exactly like healthlog/test_healthlog_host.c
# already does, and that path is the one actually exercised in this repo.
idf_component_register(
    SRCS "../../../healthlog/healthlog.c" "../../../healthlog/sha256.c"
    INCLUDE_DIRS "../../../healthlog"
    REQUIRES ""
)

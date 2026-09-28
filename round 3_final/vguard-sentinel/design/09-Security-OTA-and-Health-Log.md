# 09 — Security, OTA and the Signed Health Log (worked out to a T)

**Resolves Gap Register:** H22 (OTA), H23 (signed health log), plus the security half of H20.

## 1. Boot and flash integrity
- **Secure Boot V2** (RSA-3072; ROM → 2nd-stage bootloader → app), up to 3 eFuse key digests with revocation (`esp_ota_revoke_secure_boot_public_key`); digests write-protected after provisioning.
- **Flash Encryption** enabled with it — Secure Boot alone does not stop a desoldered-flash read-out.
- **Per-device / per-batch keys** burned at the factory station into eFuse (one-time, software-unreadable).

## 2. Network and local
- **TLS 1.3 (1.2 fallback) with mutual authentication** to the V-Guard broker; per-device client certificate whose private key lives in the **ATECC608** and never leaves it; server CA pinned.
- **BLE LE Secure Connections** (ECDH pairing) for the app; BLE advertising slowed to 5 s during outages (10 §5).

## 3. OTA — firmware and models are separate channels
| | Firmware | Model |
|---|---|---|
| Partition | two OTA app slots (A/B), `esp_ota` | two 128 KB model slots (A/B) |
| Verification | Secure Boot signature before the boot pointer flips | CRC32 + signature + `feature_schema_version` must equal the firmware's |
| Trial | post-boot self-test (cloud reachable, sensors read) | `AllocateTensors()` + one inference on a built-in golden window with expected outputs |
| Rollback | automatic to previous slot on failed self-test | automatic if trial fails or the first 5 field inferences disagree with the previous model by > 10 SoH points |
| Anti-rollback | monotonic security-version eFuse; bootloader refuses lower versions | model_version monotonic in NVS |
| Size | full image | ~100 KB per model refresh |
Rollout rings (08 §A5): canary 1 % (48–72 h) → 10 % (1 wk) → 50 % (1 wk) → 100 %, auto-halt on crash-loop, fault-event rate or confidence-distribution regression. Downloads only in the A3 upload windows (never during an outage).

## 4. Signed, tamper-evident health log (the warranty instrument)
- **Key**: ECDSA-P256 generated **inside the ATECC608** at manufacture; public key registered in V-Guard's device registry at the same factory step. (eFuse-only keys on the S3 are a lower-cost fallback with materially weaker tamper resistance; use the secure element wherever the log decides warranty.)
- **Record**: `{monotonic_counter, timestamp (DS3231-backed, 10 §6), event_data, prev_record_hash}`, SHA-256 hash-chained, each record signed. Events: full-charge detections, capacity samples, SoH grade changes, anomaly alarms, over-temperature, deep discharges, PQ events, charger setpoints applied (embedded), user overrides, firmware/model versions.
- **What a verifier can prove with only the registered public key**: (a) tampering — a hash mismatch breaks the chain; (b) deletion — a counter gap; (c) replay — the counter must strictly increase and each signature covers the counter.
- **Threat model**: *tamper* — no extractable key, so no forged plausible log; *replay* — counter + chain; *clone* — a clone needs its own registered key; ATECC608 keys are provisioned once and non-extractable, so mass cloning requires lab-grade attack, not casual tampering. Stated limitation: a secure element does not protect against a physically substituted sensor (feeding false data to an honest logger) — the log proves what the device saw, not that the sensor was untouched; sensor-plausibility checks (01 §3.4, 02 §6) are the mitigation.
- **Use**: one-tap warranty claim uploads the chain; V-Guard verifies signatures and applies the policy (e.g., "no deep discharge below 20 % more than N times; temperature stress within band") — dispute resolution from evidence rather than argument. This is the mechanism behind the report's warranty-cost claim.

## 5. Consent and data minimisation
See 08 §A4 (pseudonymisation, DPDPA consent, quasi-identifier mitigation). The health log's raw chain stays on device; only the verified claim bundle is uploaded on user action.

## References
ESP-IDF Secure Boot V2; Flash Encryption; Security overview; OTA/anti-rollback docs (ESP32-S3) · Microchip ATECC608A/B datasheet · Bluetooth Core Spec (LE Secure Connections) · ADI DS3231 datasheet.

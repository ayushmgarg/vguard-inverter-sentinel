/* firmware/main/task_config.h -- FreeRTOS task priorities and core pinning,
 * exactly per documentation/prototype/04-Self-Contained-Operation-and-Firmware.md §2.
 *
 * ESP-IDF specific (tskIDLE_PRIORITY-relative priority numbers, portNUM_PROCESSORS
 * core ids) -- included only by main.c, not by the portable engine files.
 */
#ifndef SENTINEL_TASK_CONFIG_H
#define SENTINEL_TASK_CONFIG_H

#define SENTINEL_CORE_PROTOCOL 0   /* Core 0: Wi-Fi/BLE, MQTT, OTA */
#define SENTINEL_CORE_APP      1   /* Core 1: sensing + control loop */

/* Core 1 (application core), design 04 §2 table, highest number = highest priority */
#define PRIO_HEARTBEAT    24
#define PRIO_SENSE_1HZ    20
#define PRIO_EKF          18
#define PRIO_AUTOPILOT    17
#define PRIO_PQ           15
#define PRIO_AFE_3HZ      14
#define PRIO_CYCLE_FEAT   12
#define PRIO_ML_INFER     10
#define PRIO_LOGGER        8

/* Core 0 (protocol core) -- not implemented beyond stub idle loops in this
 * prototype pass (self-contained operation needs none of these on the
 * control path, design 04 §1); kept here so main.c's task table matches the
 * design doc even though the bodies are placeholders. */
#define PRIO_APP_BLE        6
#define PRIO_MQTT_TELEMETRY 5
#define PRIO_OTA            4

#define STACK_SENSE_1HZ    3072
#define STACK_EKF          3072
#define STACK_AUTOPILOT    3072
#define STACK_CYCLE_FEAT   3072
#define STACK_ML_INFER     4096   /* sentinel_int8's largest stack array is
                                      dense1_weight-sized activations, a few KB */
#define STACK_AFE_3HZ      3072
#define STACK_PQ           3072
#define STACK_LOGGER       4096
#define STACK_HEARTBEAT    1536
#define STACK_STUB_CORE0   2048

#endif /* SENTINEL_TASK_CONFIG_H */

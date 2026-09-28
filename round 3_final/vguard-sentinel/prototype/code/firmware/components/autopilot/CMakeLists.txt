# firmware/components/autopilot -- thin ESP-IDF wrapper for code/autopilot/autopilot.c.
idf_component_register(
    SRCS "../../../autopilot/autopilot.c"
    INCLUDE_DIRS "../../../autopilot"
    REQUIRES ""
)

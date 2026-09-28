# firmware/components/nilm -- thin ESP-IDF wrapper for code/nilm/{event_detector,pzem_parser}.c.
idf_component_register(
    SRCS "../../../nilm/event_detector.c" "../../../nilm/pzem_parser.c"
    INCLUDE_DIRS "../../../nilm"
    REQUIRES ""
)

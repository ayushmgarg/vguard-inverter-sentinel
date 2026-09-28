# firmware/components/pq -- thin ESP-IDF wrapper for code/pq/pq.c.
idf_component_register(
    SRCS "../../../pq/pq.c"
    INCLUDE_DIRS "../../../pq"
    REQUIRES ""
)

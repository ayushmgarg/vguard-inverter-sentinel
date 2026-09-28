# firmware/components/ekf -- thin ESP-IDF wrapper compiling code/ekf/ekf.c by path.
# The algorithm source is NOT copied into firmware/ (single source of truth stays in
# code/ekf/, owned by module A); this component only adds it to the ESP-IDF build.
idf_component_register(
    SRCS "../../../ekf/ekf.c"
    INCLUDE_DIRS "../../../ekf"
    REQUIRES ""
)
# ekf.c is C99, host-buildable, static-allocation-only (see ekf/ekf.h doc comment) --
# no ESP-IDF-specific code inside it, so this wrapper is intentionally empty besides
# the path plumbing.

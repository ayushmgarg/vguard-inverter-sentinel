# firmware/components/tflm_wrapper -- optional esp-tflite-micro path (CONFIG_SENTINEL_USE_TFLM).
#
# This component is registered unconditionally (idf_component_register always runs),
# but tflm_wrapper.cpp's body is entirely behind `#ifdef CONFIG_SENTINEL_USE_TFLM` --
# with the option off (default) it compiles to an empty translation unit, so the
# esp-tflite-micro managed component is never pulled in or linked unless a developer
# opts in. See idf_component.yml for the dependency declaration and README.md in this
# directory for why the sentinel_int8 hand-written path is the one this repo actually
# runs and tests.
idf_component_register(
    SRCS "tflm_wrapper.cpp"
    INCLUDE_DIRS "include"
    REQUIRES "sentinel_int8"
)

target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu++17)

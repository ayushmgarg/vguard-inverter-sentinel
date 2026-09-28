# firmware/CMakeLists.txt -- ESP-IDF 5.x top-level project file.
#
# NOT run in this environment (ESP-IDF is not installed here -- see
# firmware/README.md "what was executed here"). Intended usage on a machine
# with ESP-IDF 5.x installed and sourced (`. $IDF_PATH/export.sh`):
#
#   cd firmware/
#   idf.py set-target esp32s3
#   idf.py build
#   idf.py -p /dev/ttyUSB0 flash monitor
#
cmake_minimum_required(VERSION 3.16)

# esp-tflite-micro is declared in components/tflm_wrapper/idf_component.yml and is
# fetched automatically by the IDF Component Manager on `idf.py build` -- only needed
# when CONFIG_SENTINEL_USE_TFLM=y (default n, see sdkconfig.defaults).
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(sentinel_core)

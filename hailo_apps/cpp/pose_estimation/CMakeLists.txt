cmake_minimum_required(VERSION 3.11)
project(pose_estimation CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(COMPILE_OPTIONS
    -Werror -Wall -Wextra -Wconversion
    -O3
    -Wno-reorder -Wno-ignored-qualifiers -Wno-extra -Wno-unused-local-typedefs
    -Wno-conversion -Wno-parentheses -Wno-unused-but-set-variable -Wno-array-bounds
    -Wno-unused-value
)

find_package(Threads REQUIRED)
find_package(HailoRT REQUIRED)
find_package(OpenCV REQUIRED)
message(STATUS "Found OpenCV: ${OpenCV_INCLUDE_DIRS}")

# ---- xtl / xtensor ----
# Prefer vendored headers under cpp/common/third_party to avoid toolchain/version
# mismatches. If not present, fall back to system includes.
set(THIRD_PARTY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../common/third_party")

find_path(XTL_INCLUDE_DIR xtl/xoptional.hpp
    PATH_SUFFIXES include
    PATHS
        "${THIRD_PARTY_DIR}/xtl/include"
        /usr/include
        /usr/local/include)
if (NOT XTL_INCLUDE_DIR)
    message(FATAL_ERROR "xtl headers not found. Please vendor them at ${THIRD_PARTY_DIR}/xtl/include or install xtl system-wide.")
endif()
message(STATUS "XTL_INCLUDE_DIR = ${XTL_INCLUDE_DIR}")

find_path(XTENSOR_INCLUDE_DIR xtensor/views/xview.hpp
    PATH_SUFFIXES include
    PATHS
        "${THIRD_PARTY_DIR}/xtensor/include"
        /usr/include
        /usr/local/include)
if (NOT XTENSOR_INCLUDE_DIR)
    # xtensor <= 0.24.x doesn't have xtensor/views/xview.hpp (it is xtensor/xview.hpp).
    find_path(XTENSOR_INCLUDE_DIR xtensor/xview.hpp
        PATH_SUFFIXES include
        PATHS
            "${THIRD_PARTY_DIR}/xtensor/include"
            /usr/include
            /usr/local/include)
endif()
if (NOT XTENSOR_INCLUDE_DIR)
    message(FATAL_ERROR "xtensor headers not found. Please vendor them at ${THIRD_PARTY_DIR}/xtensor/include or install xtensor system-wide.")
endif()
message(STATUS "XTENSOR_INCLUDE_DIR = ${XTENSOR_INCLUDE_DIR}")

file(GLOB SOURCES CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/*.cpp
)
list(APPEND SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/../common/toolbox.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../common/hailo_infer.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES})
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/xtensor_compat/xtensor/core")
file(WRITE "${CMAKE_BINARY_DIR}/xtensor_compat/xtensor/core/xeval.hpp" "#pragma once\n#include <xtensor/xeval.hpp>\n")

target_compile_options(${PROJECT_NAME} PRIVATE ${COMPILE_OPTIONS})

# Some toolchains (e.g., GCC 9) require this flag for C++20 concepts.
target_compile_options(${PROJECT_NAME} PRIVATE -fconcepts)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${OpenCV_INCLUDE_DIRS}
    ${XTENSOR_INCLUDE_DIR}
    ${XTL_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    HailoRT::libhailort
    Threads::Threads
    ${OpenCV_LIBS}
)
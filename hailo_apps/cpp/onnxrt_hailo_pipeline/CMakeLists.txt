cmake_minimum_required(VERSION 3.12)
project(onnxrt_hailo_pipeline LANGUAGES C CXX)

# ============================================================
# Settings
# ============================================================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Option: allow advanced users to use system/vcpkg deps instead of submodules
option(HAILO_USE_SYSTEM_DEPS "Use system-installed yaml-cpp/libcurl/xtensor instead of submodules" OFF)

# Third-party directory (submodules live here)
# <repo>/hailo_apps/cpp/onnxrt_hailo_pipeline
# <repo>/hailo_apps/cpp/external/{yaml-cpp,curl}
set(THIRD_PARTY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../external")

# ----- Compiler check (GNU only) -----
if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    if (CMAKE_CXX_COMPILER_VERSION VERSION_LESS "11.0")
        message(FATAL_ERROR
            "GCC 11+ required. Found version ${CMAKE_CXX_COMPILER_VERSION} at ${CMAKE_CXX_COMPILER}\n"
            "Fix:\n"
            "  • Install GCC 11+: sudo apt install gcc-11 g++-11\n"
            "  • Reconfigure: cmake -DCMAKE_C_COMPILER=gcc-11 -DCMAKE_CXX_COMPILER=g++-11 <src>\n"
            "  • Delete your build directory and rerun cmake.")
    endif()
endif()

# ============================================================
# Core dependencies
# ============================================================
find_package(Threads REQUIRED)
find_package(HailoRT REQUIRED)
find_package(OpenCV REQUIRED)

message(STATUS "Found OpenCV includes: ${OpenCV_INCLUDE_DIRS}")

# ============================================================
# yaml-cpp
# ============================================================
if(HAILO_USE_SYSTEM_DEPS)
    find_package(yaml-cpp REQUIRED)
else()
    if(NOT EXISTS "${THIRD_PARTY_DIR}/yaml-cpp/CMakeLists.txt")
        message(FATAL_ERROR
            "Missing submodule: yaml-cpp\n"
            "Expected path:\n"
            "  ${THIRD_PARTY_DIR}/yaml-cpp\n\n"
            "Fix:\n"
            "  git submodule update --init --recursive\n"
            "Or clone with:\n"
            "  git clone --recurse-submodules <repo>\n"
        )
    endif()

    set(YAML_CPP_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_BUILD_CONTRIB OFF CACHE BOOL "" FORCE)

    add_subdirectory(
        "${THIRD_PARTY_DIR}/yaml-cpp"
        "${CMAKE_BINARY_DIR}/_deps/yaml-cpp"
    )
endif()

if(TARGET yaml-cpp::yaml-cpp)
    set(YAMLCPP_TARGET yaml-cpp::yaml-cpp)
elseif(TARGET yaml-cpp)
    set(YAMLCPP_TARGET yaml-cpp)
else()
    message(FATAL_ERROR "yaml-cpp target was not created. Check yaml-cpp submodule/build.")
endif()

# ============================================================
# libcurl
# ============================================================
if(HAILO_USE_SYSTEM_DEPS)
    find_package(CURL REQUIRED)
else()
    if(NOT EXISTS "${THIRD_PARTY_DIR}/curl/CMakeLists.txt")
        message(FATAL_ERROR
            "Missing submodule: curl\n"
            "Expected path:\n"
            "  ${THIRD_PARTY_DIR}/curl\n\n"
            "Fix:\n"
            "  git submodule update --init --recursive\n"
            "Or clone with:\n"
            "  git clone --recurse-submodules <repo>\n"
        )
    endif()

    set(BUILD_CURL_EXE OFF CACHE BOOL "" FORCE)
    set(CURL_DISABLE_TESTS ON CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

    # Avoid optional deps that break Windows builds (LibPSL/Brotli/Zstd/NGHTTP2...)
    set(CURL_USE_LIBPSL OFF CACHE BOOL "" FORCE)
    set(CURL_BROTLI OFF CACHE BOOL "" FORCE)
    set(CURL_ZSTD OFF CACHE BOOL "" FORCE)
    set(USE_NGHTTP2 OFF CACHE BOOL "" FORCE)
    set(CURL_DISABLE_LDAP ON CACHE BOOL "" FORCE)
    set(CURL_DISABLE_LDAPS ON CACHE BOOL "" FORCE)

    if(WIN32)
        set(CURL_USE_SCHANNEL ON CACHE BOOL "" FORCE)
        set(CURL_USE_OPENSSL OFF CACHE BOOL "" FORCE)
    endif()

    add_subdirectory(
        "${THIRD_PARTY_DIR}/curl"
        "${CMAKE_BINARY_DIR}/_deps/curl"
    )

    # Some curl builds export "libcurl" not "CURL::libcurl"
    if(TARGET libcurl AND NOT TARGET CURL::libcurl)
        add_library(CURL::libcurl ALIAS libcurl)
    endif()
endif()

if(NOT TARGET CURL::libcurl)
    message(FATAL_ERROR "libcurl target missing (CURL::libcurl). Check curl submodule/build.")
endif()

# ============================================================
# ONNX Runtime
# - Linux: detect under /opt/*
# - Windows: allow ONNXRUNTIME_DIR cache var OR env var ONNXRUNTIME_DIR
# ============================================================
set(ONNXRUNTIME_DIR "" CACHE PATH "Path to ONNX Runtime root directory (contains include/ and lib/)")

if (NOT ONNXRUNTIME_DIR)
    if(DEFINED ENV{ONNXRUNTIME_DIR})
        set(ONNXRUNTIME_DIR "$ENV{ONNXRUNTIME_DIR}")
    endif()
endif()

if (NOT ONNXRUNTIME_DIR)
    if (WIN32)
        message(FATAL_ERROR
            "ONNXRUNTIME_DIR is not set on Windows.\n"
            "Fix:\n"
            "  - Set -DONNXRUNTIME_DIR=C:/path/to/onnxruntime\n"
            "  - Or set env var ONNXRUNTIME_DIR\n"
            "Expected layout:\n"
            "  <ONNXRUNTIME_DIR>/include\n"
            "  <ONNXRUNTIME_DIR>/lib\n")
    else()
        file(GLOB ALL_SUBDIRS "/opt/*")
        foreach(DIR ${ALL_SUBDIRS})
            if (IS_DIRECTORY "${DIR}" AND "${DIR}" MATCHES ".*onnxruntime.*")
                set(ONNXRUNTIME_DIR "${DIR}")
                break()
            endif()
        endforeach()
    endif()
endif()

if (ONNXRUNTIME_DIR)
    message(STATUS "Using ONNX Runtime directory: ${ONNXRUNTIME_DIR}")

    find_path(ONNXRUNTIME_INCLUDE_DIR
        NAMES onnxruntime_cxx_api.h
        HINTS "${ONNXRUNTIME_DIR}/include"
        REQUIRED
    )

    find_library(ONNXRUNTIME_LIB
        NAMES onnxruntime
        HINTS "${ONNXRUNTIME_DIR}/lib"
        REQUIRED
    )
else()
    message(FATAL_ERROR "Failed to locate ONNX Runtime. Set ONNXRUNTIME_DIR.")
endif()

# ============================================================
# xtl + xtensor (header-only) - ExternalProject install (WORKING STYLE)
# ============================================================
# ---- ExternalProject for xtl/xtensor (header-only) ----
include(ExternalProject)

# A single install prefix where headers will land:
set(EXTERNAL_PREFIX ${CMAKE_BINARY_DIR}/external)

ExternalProject_Add(xtl-test
    GIT_REPOSITORY https://github.com/xtensor-stack/xtl
    GIT_TAG 0.7.7
    CMAKE_ARGS -DCMAKE_INSTALL_PREFIX=${EXTERNAL_PREFIX}
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    INSTALL_DIR ${EXTERNAL_PREFIX}
)

ExternalProject_Add(xtensor-test
    DEPENDS xtl-test
    GIT_REPOSITORY https://github.com/xtensor-stack/xtensor
    GIT_TAG 0.24.6
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${EXTERNAL_PREFIX}
        -Dxtl_DIR=${EXTERNAL_PREFIX}/share/cmake/xtl
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    INSTALL_DIR ${EXTERNAL_PREFIX}
)

# xtensor include path (after external install)
set(XTENSOR_INCLUDE_DIR ${EXTERNAL_PREFIX}/include)

# ============================================================
# Sources
# ============================================================
add_executable(${PROJECT_NAME}
    onnxrt_hailo_pipeline.cpp
    onnx_decode.cpp
    instance_seg_postprocess.cpp
    ../common/toolbox.cpp
    ../common/hailo_infer.cpp
    ../common/resources_manager.cpp
)

add_dependencies(${PROJECT_NAME} xtl-test xtensor-test)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${OpenCV_INCLUDE_DIRS}
    ${ONNXRUNTIME_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${XTENSOR_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
    ${CMAKE_BINARY_DIR}/external/include
)

# ============================================================
# Compile options (Linux vs Windows)
# ============================================================
if(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE
        /W4 /O2
        /EHsc
        /permissive-
        /Zc:__cplusplus
    )
    target_compile_definitions(${PROJECT_NAME} PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
else()
    target_compile_options(${PROJECT_NAME} PRIVATE
        -O3 -DNDEBUG -Wall -Wextra
        -Wno-reorder -Wno-ignored-qualifiers -Wno-unused-local-typedefs
        -Wno-parentheses -Wno-array-bounds -Wno-unused-value
        -Wno-conversion -Wno-unused-parameter -Wno-missing-field-initializers
        -Wno-sign-compare -Wno-uninitialized
    )
endif()

# ============================================================
# Link
# ============================================================
target_link_libraries(${PROJECT_NAME} PRIVATE
    Threads::Threads
    HailoRT::libhailort
    ${OpenCV_LIBS}
    ${YAMLCPP_TARGET}
    CURL::libcurl
    ${ONNXRUNTIME_LIB}
)

# ============================================================
# Copy repo-level YAML next to the executable:
# <exe_dir>/config/resources_config.yaml
# ============================================================
set(HAILO_APPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")  # onnxrt_hailo_pipeline -> cpp -> hailo_apps
set(RESOURCES_YAML_SRC "${HAILO_APPS_ROOT}/config/resources_config.yaml")

if(NOT EXISTS "${RESOURCES_YAML_SRC}")
    message(FATAL_ERROR "resources_config.yaml not found at: ${RESOURCES_YAML_SRC}")
endif()

add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:${PROJECT_NAME}>/config"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${RESOURCES_YAML_SRC}"
            "$<TARGET_FILE_DIR:${PROJECT_NAME}>/config/resources_config.yaml"
    COMMENT "Copy resources_config.yaml next to the executable"
)
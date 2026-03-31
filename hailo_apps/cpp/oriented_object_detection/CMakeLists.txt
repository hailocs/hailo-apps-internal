cmake_minimum_required(VERSION 3.16)
project(oriented_obj_det LANGUAGES C CXX)

# ============================================================
# Settings
# ============================================================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Option: allow advanced users to use system/vcpkg deps instead of submodules
option(HAILO_USE_SYSTEM_DEPS "Use system-installed yaml-cpp/libcurl instead of submodules" OFF)

# Third-party directory (submodules live here)
# <repo>/hailo_apps/cpp/oriented_object_detection
# <repo>/hailo_apps/cpp/external/{yaml-cpp,curl}
set(THIRD_PARTY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../external")

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
# Sources
# ============================================================
file(GLOB SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/*.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/utils/*.cpp
)

list(APPEND SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/../common/toolbox.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../common/hailo_infer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../common/resources_manager.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES})

target_include_directories(${PROJECT_NAME} PRIVATE
    ${OpenCV_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/utils
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

# ============================================================
# Compile options (Linux vs Windows)
# ============================================================
if(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE
        /W4 /O2
        /permissive-
        /Zc:__cplusplus
        /EHsc
        /openmp
    )
    target_compile_definitions(${PROJECT_NAME} PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
else()
    # Base compilation options (portable on GCC/Clang)
    target_compile_options(${PROJECT_NAME} PRIVATE
        -Wall -Wextra -O3
        -Wno-ignored-qualifiers
        -Wno-extra
        -Wno-stringop-truncation
        -Wno-reorder
        -Wno-unused-parameter
        -fopenmp
    )

    # Add AVX2/FMA only if compiler supports them (x86)
    include(CheckCXXCompilerFlag)
    check_cxx_compiler_flag("-mavx2" HAS_AVX2)
    check_cxx_compiler_flag("-mfma"  HAS_FMA)
    if (HAS_AVX2)
        target_compile_options(${PROJECT_NAME} PRIVATE -mavx2)
    endif()
    if (HAS_FMA)
        target_compile_options(${PROJECT_NAME} PRIVATE -mfma)
    endif()
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
)

# ============================================================
# Copy repo-level YAML next to the executable:
# <exe_dir>/config/resources_config.yaml
# ============================================================
set(HAILO_APPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")  # oriented_object_detection -> cpp -> hailo_apps
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
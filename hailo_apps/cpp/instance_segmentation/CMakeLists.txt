cmake_minimum_required(VERSION 3.16)
project(instance_segmentation LANGUAGES C CXX)

# ============================================================
# Settings
# ============================================================
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Option: allow advanced users to use system/vcpkg deps instead of submodules
option(HAILO_USE_SYSTEM_DEPS "Use system-installed yaml-cpp/libcurl/xtensor instead of submodules" OFF)

# Third-party directory (submodules live here)
# <repo>/hailo_apps/cpp/instance_segmentation
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
# xtl + xtensor (header-only)
# - Use system/vcpkg if exists, otherwise FetchContent into build/_deps
# - Not "external install" folder (so MSVC always finds headers)
# ============================================================
if(HAILO_USE_SYSTEM_DEPS)
    find_package(xtl CONFIG REQUIRED)
    find_package(xtensor CONFIG REQUIRED)
    set(USE_SYSTEM_XTENSOR ON)
else()
    message(STATUS "Fetching xtl/xtensor (build tree only)")
    include(FetchContent)

    FetchContent_Declare(
        xtl
        GIT_REPOSITORY https://github.com/xtensor-stack/xtl.git
        GIT_TAG        0.7.7
    )
    FetchContent_Declare(
        xtensor
        GIT_REPOSITORY https://github.com/xtensor-stack/xtensor.git
        GIT_TAG        0.26.0
    )
    FetchContent_MakeAvailable(xtl xtensor)
    set(USE_SYSTEM_XTENSOR OFF)
endif()

# ============================================================
# Sources
# ============================================================
add_executable(${PROJECT_NAME}
    instance_segmentation.cpp
    instance_seg_postprocess.cpp
    ../common/toolbox.cpp
    ../common/hailo_infer.cpp
    ../common/resources_manager.cpp
)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${OpenCV_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

# xtensor include path
if(USE_SYSTEM_XTENSOR)
    target_link_libraries(${PROJECT_NAME} PRIVATE xtl xtensor)
else()
    target_include_directories(${PROJECT_NAME} PRIVATE
        ${xtl_SOURCE_DIR}/include
        ${xtensor_SOURCE_DIR}/include
    )
endif()

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
)

# ============================================================
# Copy repo-level YAML next to the executable:
# <exe_dir>/config/resources_config.yaml
# ============================================================
set(HAILO_APPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")  # instance_segmentation -> cpp -> hailo_apps
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
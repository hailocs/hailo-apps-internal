cmake_minimum_required(VERSION 3.16)
project(gesture_detection)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(COMPILE_OPTIONS -Wall -Wextra -O3 -fconcepts -Wno-ignored-qualifiers -Wno-extra -Wno-reorder)

find_package(Threads REQUIRED)
find_package(HailoRT REQUIRED)
find_package(OpenCV REQUIRED)

message(STATUS "Found OpenCV: " ${OpenCV_INCLUDE_DIRS})

set(SOURCES
    gesture_detection.cpp
    palm_detection.cpp
    hand_landmark.cpp
    gesture_classify.cpp
    camera_utils.cpp
    ../common/hailo_infer.cpp
)

include_directories(
    ${OpenCV_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

add_executable(${PROJECT_NAME} ${SOURCES})
target_compile_options(${PROJECT_NAME} PRIVATE ${COMPILE_OPTIONS})
target_link_libraries(${PROJECT_NAME}
    Threads::Threads
    HailoRT::libhailort
    ${OpenCV_LIBS}
    stdc++fs
)

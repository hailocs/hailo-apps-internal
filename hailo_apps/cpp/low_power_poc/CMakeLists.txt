cmake_minimum_required(VERSION 3.16)
project(low_power_poc LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Threads REQUIRED)
find_package(HailoRT REQUIRED)

add_executable(${PROJECT_NAME} low_power_poc.cpp)

target_link_libraries(${PROJECT_NAME} PRIVATE
    HailoRT::libhailort
    Threads::Threads
)

target_compile_options(${PROJECT_NAME} PRIVATE -Wall -Wextra)

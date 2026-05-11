/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 *
 * BgShmReader - RAII wrapper around shm_open + mmap for read-only access
 * to a POSIX shared-memory segment created by Python's
 * multiprocessing.shared_memory.SharedMemory.
 */
#pragma once

#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

class BgShmReader {
public:
    BgShmReader(const std::string &name, std::size_t bytes)
        : fd_(-1), map_(nullptr), bytes_(bytes)
    {
        // Python's multiprocessing.shared_memory prefixes segment names
        // with "/" when calling shm_open under the hood.
        const std::string posix_name = "/" + name;
        fd_ = shm_open(posix_name.c_str(), O_RDONLY, 0);
        if (fd_ < 0) {
            throw std::runtime_error("shm_open failed for " + posix_name);
        }
        map_ = mmap(nullptr, bytes_, PROT_READ, MAP_SHARED, fd_, 0);
        if (map_ == MAP_FAILED) {
            ::close(fd_);
            fd_ = -1;
            throw std::runtime_error("mmap failed for " + posix_name);
        }
    }
    BgShmReader(const BgShmReader &) = delete;
    BgShmReader &operator=(const BgShmReader &) = delete;
    ~BgShmReader() {
        if (map_ && map_ != MAP_FAILED) ::munmap(map_, bytes_);
        if (fd_ >= 0) ::close(fd_);
    }
    const uint8_t *data() const { return static_cast<const uint8_t*>(map_); }
    std::size_t bytes() const { return bytes_; }
private:
    int fd_;
    void *map_;
    std::size_t bytes_;
};

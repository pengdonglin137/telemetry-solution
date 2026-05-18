# Copyright 2025-2026 Arm Limited
# SPDX-License-Identifier: BSD-3-Clause

cmake_minimum_required(VERSION 3.20)

project(sysstress LANGUAGES C CXX)

add_subdirectory(contention_test)
add_subdirectory(slc_bw_test)
add_subdirectory(mem_bw_test)

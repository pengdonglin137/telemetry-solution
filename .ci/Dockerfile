
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Arm Limited

ARG DOCKER_BASE=ubuntu:noble
FROM ${DOCKER_BASE}

ARG APT_PORTS_MIRROR_URL
ARG APT_ARCHIVE_MIRROR_URL
ARG APT_SECURITY_MIRROR_URL

ENV DEBIAN_FRONTEND=noninteractive 

RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    APT_SOURCES_FILES="/etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources"; \
    [ -z "${APT_PORTS_MIRROR_URL}" ] || sed -E -i \
      -e "s|https?://ports\\.ubuntu\\.com/ubuntu-ports|${APT_PORTS_MIRROR_URL}|g" \
      $APT_SOURCES_FILES 2>/dev/null || true; \
    [ -z "${APT_ARCHIVE_MIRROR_URL}" ] || sed -E -i \
      -e "s|https?://archive\\.ubuntu\\.com/ubuntu|${APT_ARCHIVE_MIRROR_URL}|g" \
      $APT_SOURCES_FILES 2>/dev/null || true; \
    [ -z "${APT_SECURITY_MIRROR_URL}" ] || sed -E -i \
      -e "s|https?://security\\.ubuntu\\.com/ubuntu|${APT_SECURITY_MIRROR_URL}|g" \
      $APT_SOURCES_FILES 2>/dev/null || true; \
    apt-get update; \
    apt-get -y install software-properties-common; \
    add-apt-repository -y ppa:deadsnakes/ppa; \
    apt-get update; \
    apt-get -y install gcc make zip git cmake \
                          python3 python3-pip python3-venv \
                          python3.10 python3.11 python3.12 python3.13 python3.14 \
                          curl openjdk-21-jdk jq; \
    if [ "$(uname -m)" = "aarch64" ]; then \
        apt-get -y install gcc-10; \
    else \
        apt-get -y install gcc-10-aarch64-linux-gnu g++-10-aarch64-linux-gnu gcc-aarch64-linux-gnu; \
    fi; \
    rm -rf /var/lib/apt/lists/* /usr/share/man/* /usr/share/doc/*;

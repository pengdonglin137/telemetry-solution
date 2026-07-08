# SPDX-License-Identifier: Apache-2.0
# Copyright 2023-2025 Arm Limited

.PHONY: test
test:
	@uv run --group tox tox

.PHONY: install
install:
	@uv sync --no-dev

.PHONY: lint
lint:
	@uv run --group lint pre-commit run --show-diff-on-failure --all-files

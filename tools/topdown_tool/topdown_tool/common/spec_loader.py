# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

"""Shared helpers for loading telemetry specification JSON files."""

import json
from pathlib import Path
from typing import Type, TypeVar, Union

import jsonschema
from pydantic import BaseModel
from pydantic import ValidationError

T = TypeVar("T", bound=BaseModel)


def load_spec_json(
    path: Union[str, Path],
    schema_dir: Union[str, Path],
    model_cls: Type[T],
    *,
    duplicate_policy: str = "log",
    encoding: str = "utf-8",
) -> T:
    """Read JSON, apply $schema validation, and load into a Pydantic model.

    Args:
        path: Specification JSON file to load.
        schema_dir: Directory containing referenced JSON schemas.
        model_cls: Pydantic model class to validate into.
        duplicate_policy: Duplicate handling policy passed via Pydantic context.
        encoding: File encoding for spec and schema files.

    Returns:
        An instance of ``model_cls``.
    """
    # pylint: disable=too-many-arguments, too-many-locals

    path = Path(path)
    schema_dir = Path(schema_dir)
    try:
        with path.open(encoding=encoding) as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                # Normalize all parsing/validation errors to ValueError for a consistent surface;
                # include path and location to avoid leaking raw JSONDecodeError messages upstream.
                raise ValueError(
                    f"JSON file {path} content is not valid. Please check the error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
                ) from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"File not found: {exc.filename}. Please check that the file exists."
        ) from exc

    instance = dict(data)
    schema_label = instance.get("$schema")
    if schema_label:
        schema_path = schema_dir / schema_label
        try:
            with schema_path.open(encoding=encoding) as schema_handle:
                try:
                    schema = json.load(schema_handle)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Schema file {schema_path} content is not valid. Please check the error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
                    ) from exc
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"File not found: {exc.filename}. Please check that the file exists."
            ) from exc

        # JSON Schema validation ignores $schema; remove it unless explicitly retained.
        schema_instance = dict(instance)
        schema_instance.pop("$schema", None)
        try:
            jsonschema.validate(instance=schema_instance, schema=schema)
        except jsonschema.exceptions.ValidationError as exc:
            raise ValueError(
                f"Schema validation failed for {path} with the following error: {exc.message}\nPlease check the JSON file and the schema."
            ) from exc

    instance.pop("$schema", None)  # Strip $schema so Pydantic extra="forbid" models accept the payload.

    try:
        model = model_cls.model_validate(instance, context={"duplicate_policy": duplicate_policy})
    except ValidationError as exc:
        raise ValueError(
            f"Model validation failed for {path} with the following error: {exc}\nPlease check the JSON file against the expected data model."
        ) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise ValueError(
            f"Model loading failed for {path} with the following error: {exc}\nPlease check the JSON file and the model validation logic."
        ) from exc

    return model

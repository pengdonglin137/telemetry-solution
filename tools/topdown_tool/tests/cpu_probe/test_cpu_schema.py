# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Arm Limited

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_DIR = REPOSITORY_ROOT / "data" / "pmu" / "cpu" / "schemas"
SPECIFICATION_DIR = REPOSITORY_ROOT / "data" / "pmu" / "cpu" / "specifications"
SCHEMA_NAMES = ("v1.0.schema.json", "v1.2.schema.json")
BASE_SPECIFICATION = SPECIFICATION_DIR / "neoverse" / "neoverse_n3_r0p0_pmu.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def assert_schema_failure(validator, document, path, keyword=None):
    # Check the affected location, allowing equivalent schema implementations
    # to report multiple errors or errors in more specific child properties.
    errors = list(validator.iter_errors(document))
    assert any(
        list(error.absolute_path)[:len(path)] == path
        and (keyword is None or error.validator == keyword)
        for error in errors
    ), errors


# These tests validate the CPU JSON Schema contracts themselves: the schemas
# must conform to Draft 2020-12 and enforce their intended structural rules.
@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_cpu_schema_is_valid_draft_2020_12(schema_name):
    Draft202012Validator.check_schema(load_json(SCHEMA_DIR / schema_name))


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("selector", [None, "", 1])
def test_schema_requires_nonempty_string_selector(schema_name, selector):
    document = load_json(BASE_SPECIFICATION)
    if selector is None:
        document.pop("$schema")
    else:
        document["$schema"] = selector
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))

    errors = list(validator.iter_errors(document))
    if selector is None:
        assert any(error.validator == "required" and "$schema" in error.message for error in errors)
    else:
        assert any(list(error.absolute_path) == ["$schema"] for error in errors)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_accepts_selector_without_filename_constraint(schema_name):
    document = load_json(BASE_SPECIFICATION)
    document["$schema"] = "cpu-telemetry.schema.json"
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))

    validator.validate(document)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_rejects_unknown_root_property(schema_name):
    document = load_json(BASE_SPECIFICATION)
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    validator.validate(document)
    document["unexpected"] = True

    assert_schema_failure(validator, document, [], "additionalProperties")


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_rejects_conflicting_event_origins(schema_name):
    document = load_json(BASE_SPECIFICATION)
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    validator.validate(document)
    event_name = "INST_RETIRED"
    event = document["events"][event_name]
    event["architecture_defined"] = True
    event["product_defined"] = True
    event["product_defined_attributes"] = {"debug": False}

    assert_schema_failure(validator, document, ["events", event_name])


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_rejects_duplicate_event_access(schema_name):
    document = load_json(BASE_SPECIFICATION)
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    validator.validate(document)
    event_name = "INST_RETIRED"
    document["events"][event_name]["accesses"] = ["PMU", "PMU"]

    assert_schema_failure(
        validator,
        document,
        ["events", event_name, "accesses"],
        "uniqueItems",
    )


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_rejects_unknown_nested_event_property(schema_name):
    document = load_json(BASE_SPECIFICATION)
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    validator.validate(document)
    event_name = "INST_RETIRED"
    document["events"][event_name]["unexpected"] = True

    assert_schema_failure(
        validator,
        document,
        ["events", event_name],
        "additionalProperties",
    )


INTEGER_FIELDS = (
    ("ProductConfiguration", "implementer", "hex", 0, 255, 2),
    ("ProductConfiguration", "part_num", "hex", 0, 4095, 3),
    ("ProductConfiguration", "major_revision", "decimal", 0, 15, 0),
    ("ProductConfiguration", "minor_revision", "decimal", 0, 15, 0),
    ("ProductConfiguration", "num_slots", "integer", 1, 255, 0),
    ("ProductConfiguration", "num_bus_slots", "integer", 0, 255, 0),
    ("Event", "code", "hex", 0, 65535, 4),
)


def field_representations(value, representation, digits):
    if representation == "hex":
        return (hex(value), f"0x{value:0{digits}X}")
    if representation == "decimal":
        return (str(value),)
    return (value, float(value))


def field_validator(schema_name, definition, field):
    schema = load_json(SCHEMA_DIR / schema_name)
    return Draft202012Validator({
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}/properties/{field}",
    })


# Preserve each field's established encoding and check its numerical bounds.
# Complete-document compatibility is tested through the unchanged CPU model.
@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("definition,field,representation,minimum,maximum,digits", INTEGER_FIELDS)
def test_integer_fields_accept_established_encoding_at_boundaries(
    schema_name, definition, field, representation, minimum, maximum, digits
):
    validator = field_validator(schema_name, definition, field)
    for value in (minimum, 10, maximum):
        for encoded in field_representations(value, representation, digits):
            validator.validate(encoded)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("definition,field,representation,minimum,maximum,digits", INTEGER_FIELDS)
def test_integer_fields_reject_out_of_range_and_wrong_encodings(
    schema_name, definition, field, representation, minimum, maximum, digits
):
    validator = field_validator(schema_name, definition, field)
    invalid = [True, False, None, 1.5, "1.0", "1e1", " 10", "10 ", "10\n", "+10",
               "0X0A", "0b10", "0o10", "0x", "", "0xG"]
    if representation == "hex":
        invalid.extend([10, 10.0, "10", "0x" + "0" * (digits + 1)])
    elif representation == "decimal":
        invalid.extend([10, 10.0, "0xA", "0010"])
    else:
        invalid.extend(["10", "0xA", "0010"])
    for value in (-1, minimum - 1, maximum + 1):
        invalid.extend(field_representations(value, representation, digits))
    for encoded in invalid:
        assert not validator.is_valid(encoded), (field, encoded)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_bus_slot_compatibility_exception_requires_json_integer(schema_name):
    validator = field_validator(schema_name, "ProductConfiguration", "num_bus_slots")
    for encoded in (999, 999.0):
        validator.validate(encoded)
    for encoded in (998, 1000, "999", "0x3e7"):
        assert not validator.is_valid(encoded)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("pointer,member", [
    ("Metric/properties/events", "INST_RETIRED"),
    ("FunctionGroup/properties/events", "INST_RETIRED"),
    ("MetricGroup/properties/metrics", "frontend_bound"),
    ("StageGroupList", "Topdown_L1"),
    ("DecisionTree/properties/root_nodes", "frontend_bound"),
])
def test_reference_lists_reject_duplicate_members(schema_name, pointer, member):
    schema = load_json(SCHEMA_DIR / schema_name)
    validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{pointer}"})
    validator.validate([member])
    errors = list(validator.iter_errors([member, member]))
    assert any(error.validator == "uniqueItems" for error in errors)


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_decision_tree_rejects_identical_node_objects(schema_name):
    document = load_json(BASE_SPECIFICATION)
    nodes = document["methodologies"]["topdown_methodology"]["decision_tree"]["metrics"]
    nodes.append(copy.deepcopy(nodes[0]))
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    errors = list(validator.iter_errors(document))
    assert any(
        error.validator == "uniqueItems"
        and list(error.absolute_path) == [
            "methodologies", "topdown_methodology", "decision_tree", "metrics"
        ]
        for error in errors
    )


# The methodology has named, required stages. Their cross-references and
# disjoint membership need semantic validation, not JSON Schema validation.
@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("path,missing", [
    (("methodologies",), "topdown_methodology"),
    (("methodologies", "topdown_methodology", "metric_grouping"), "stage_1"),
    (("methodologies", "topdown_methodology", "metric_grouping"), "stage_2"),
])
def test_schema_requires_topdown_methodology_and_stages(schema_name, path, missing):
    document = load_json(BASE_SPECIFICATION)
    target = document
    for key in path:
        target = target[key]
    del target[missing]
    validator = Draft202012Validator(load_json(SCHEMA_DIR / schema_name))
    errors = list(validator.iter_errors(document))
    assert any(
        error.validator == "required" and list(error.absolute_path) == list(path)
        and missing in error.message
        for error in errors
    )


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
@pytest.mark.parametrize("definition,field", [
    ("StageMap", "stage_2"),
    ("MetricTree", "next_items"),
])
def test_schema_allows_empty_stage2_and_terminal_branch(schema_name, definition, field):
    # A required array is not necessarily a non-empty array.
    field_validator(schema_name, definition, field).validate([])


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_stage2_group_need_not_be_recommended_by_tree(schema_name):
    document = load_json(BASE_SPECIFICATION)
    methodology = document["methodologies"]["topdown_methodology"]
    stages = methodology["metric_grouping"]
    group_name = stages["stage_2"][0]
    assert group_name in document["groups"]["metrics"]
    assert group_name not in stages["stage_1"]
    for node in methodology["decision_tree"]["metrics"]:
        node["next_items"] = [item for item in node["next_items"] if item != group_name]
    Draft202012Validator(load_json(SCHEMA_DIR / schema_name)).validate(document)

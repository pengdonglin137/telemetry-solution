# SPDX-License-Identifier: Apache-2.0
# Copyright 2022-2026 Arm Limited

import json

import categorise
import pytest

grouper = categorise.ArmDataEventGrouper()


def test_redundant():
    for mnemonic, group in grouper.mnemonic_matches.items():
        regex_group = grouper.regex_group(mnemonic)

        # Mnemonic matches are redundant if they are matched by a regex
        assert regex_group is None


def test_telemetry_duplicate_group_membership_uses_override(tmp_path):
    spec = {
        "groups": {
            "function": {
                "Spec_Operation": {"events": ["SVE_INST_SPEC"]},
                "SVE": {"events": ["SVE_INST_SPEC"]},
            }
        }
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))

    override_path = tmp_path / "overrides.json"
    override_path.write_text(json.dumps({"SVE_INST_SPEC": "SVE"}))

    telemetry_grouper = categorise.TelemetryEventGrouper(path_to_overrides=str(override_path))
    assert telemetry_grouper.get_groups("SVE_INST_SPEC", str(spec_path)) == ["sve"]


def test_telemetry_ambiguous_group_membership_without_override_fails(tmp_path):
    spec = {
        "groups": {
            "function": {
                "Spec_Operation": {"events": ["SVE_INST_SPEC"]},
                "SVE": {"events": ["SVE_INST_SPEC"]},
            }
        }
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))

    override_path = tmp_path / "overrides.json"
    override_path.write_text("{}")

    telemetry_grouper = categorise.TelemetryEventGrouper(path_to_overrides=str(override_path))
    with pytest.raises(AssertionError, match="Ambiguous telemetry function groups"):
        telemetry_grouper.get_groups("SVE_INST_SPEC", str(spec_path))


def test_telemetry_override_group_must_match_candidates(tmp_path):
    spec = {
        "groups": {
            "function": {
                "Spec_Operation": {"events": ["SVE_INST_SPEC"]},
                "SVE": {"events": ["SVE_INST_SPEC"]},
            }
        }
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))

    override_path = tmp_path / "overrides.json"
    override_path.write_text(json.dumps({"SVE_INST_SPEC": "General"}))

    telemetry_grouper = categorise.TelemetryEventGrouper(path_to_overrides=str(override_path))
    with pytest.raises(AssertionError, match="is not one of the candidate groups"):
        telemetry_grouper.get_groups("SVE_INST_SPEC", str(spec_path))

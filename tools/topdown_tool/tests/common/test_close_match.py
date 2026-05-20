# SPDX-License-Identifier: Apache-2.0

from topdown_tool.common.close_match import (
    format_did_you_mean,
    format_invalid_group_error,
    format_unknown_names_with_suggestions,
    get_close_name_match,
)


def test_get_close_name_match_returns_canonical_name() -> None:
    normalized_to_canonical = {
        "stage1leftgroup": "stage1_left_group",
        "stage1rightgroup": "stage1_right_group",
    }
    assert get_close_name_match("stage1_left_grup", normalized_to_canonical) == "stage1_left_group"


def test_get_close_name_match_returns_none_when_no_match() -> None:
    normalized_to_canonical = {
        "stage1leftgroup": "stage1_left_group",
    }
    assert get_close_name_match("xyz", normalized_to_canonical) is None


def test_format_did_you_mean() -> None:
    assert format_did_you_mean("stage1_left_group") == 'did you mean "stage1_left_group"?'
    assert format_did_you_mean(None) == ""


def test_format_unknown_names_with_suggestions() -> None:
    unknown = [
        ("foo", None),
        ("bar", "baz"),
    ]
    assert format_unknown_names_with_suggestions(unknown) == '"foo", "bar" (did you mean "baz"?)'


def test_format_invalid_group_error() -> None:
    assert format_invalid_group_error("grp", "grp1") == '"grp" is not a valid group. did you mean "grp1"?'

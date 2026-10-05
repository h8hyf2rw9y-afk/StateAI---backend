"""
The structural guarantee behind "the LLM cannot generate arbitrary
database column names": RenovaReadableField, RenovaFilterField and
RenovaFilterOperator are closed Pydantic Literals. These tests prove the
rejection happens at the schema itself -- before any resolver, any query,
or any real LLM provider is involved -- which is what makes it a
guarantee rather than a convention every caller has to remember to check.
"""

import pytest
from pydantic import ValidationError

from app.schemas.renova_chat import ParsedRenovaQuestion, RenovaCaseFilter


def test_an_arbitrary_case_field_is_rejected():
    with pytest.raises(ValidationError):
        ParsedRenovaQuestion(intent="case_field", field="whatever_the_model_wants")


@pytest.mark.parametrize("forbidden_field", ["nss", "credit_number", "ine_front", "ine_back", "owner_phone_plain"])
def test_sensitive_or_nonexistent_fields_cannot_be_selected_for_case_field(forbidden_field):
    with pytest.raises(ValidationError):
        ParsedRenovaQuestion(intent="case_field", field=forbidden_field)


@pytest.mark.parametrize("internal_field", ["organization_id", "id", "nss_encrypted", "credit_number_encrypted", "ine_front_encrypted", "ine_back_encrypted"])
def test_internal_and_encrypted_columns_cannot_be_selected_for_case_field(internal_field):
    with pytest.raises(ValidationError):
        ParsedRenovaQuestion(intent="case_field", field=internal_field)


def test_an_arbitrary_filter_field_is_rejected():
    with pytest.raises(ValidationError):
        RenovaCaseFilter(field="nss_encrypted", operator="equals", value="x")


def test_an_arbitrary_filter_operator_is_rejected():
    with pytest.raises(ValidationError):
        RenovaCaseFilter(field="status", operator="raw_sql", value="1=1")


def test_a_raw_sql_style_value_is_still_just_a_bounded_string_not_executed():
    """The Pydantic layer only bounds length/type; app/renova_chat/filters.py is what refuses an unrecognized value -- see test_renova_chat_filters.py."""
    filter_ = RenovaCaseFilter(field="municipality", operator="equals", value="'; DROP TABLE renova_cases; --")
    assert filter_.value == "'; DROP TABLE renova_cases; --"  # stored as a literal bound parameter value, never concatenated into SQL


def test_filter_field_literal_excludes_every_sensitive_or_internal_column():
    import typing

    from app.schemas.renova_chat import RenovaFilterField

    allowed = set(typing.get_args(RenovaFilterField))
    assert allowed.isdisjoint({
        "nss", "credit_number", "nss_encrypted", "credit_number_encrypted",
        "ine_front_encrypted", "ine_back_encrypted", "owner_phone", "spouse_phone",
        "organization_id", "id", "assigned_user_id", "created_by_user_id",
    })


def test_readable_field_literal_excludes_every_sensitive_or_internal_column():
    import typing

    from app.schemas.renova_chat import RenovaReadableField

    allowed = set(typing.get_args(RenovaReadableField))
    assert allowed.isdisjoint({
        "nss", "credit_number", "nss_encrypted", "credit_number_encrypted",
        "ine_front_encrypted", "ine_back_encrypted",
        "organization_id", "id", "assigned_user_id", "created_by_user_id",
    })

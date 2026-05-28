"""
Tests for validators.py — parameter validation functions.
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validators import (
    ValidationError,
    validate_not_empty,
    validate_length,
    validate_enum,
    validate_int_range,
    ALLOWED_CATEGORIES,
    ALLOWED_SEVERITIES,
    ALLOWED_ERROR_CATEGORIES,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_SCOPES,
    ALLOWED_RELATIONS,
    ALLOWED_SOURCE_TYPES,
)


class TestValidateNotEmpty:
    """Test validate_not_empty function."""

    def test_empty_string_raises(self):
        """Empty string should raise ValidationError."""
        with pytest.raises(ValidationError, match="name 不能为空"):
            validate_not_empty("", "name")

    def test_whitespace_only_raises(self):
        """Whitespace-only string should raise ValidationError."""
        with pytest.raises(ValidationError, match="title 不能为空"):
            validate_not_empty("   ", "title")

    def test_newline_only_raises(self):
        """Newline-only string should raise."""
        with pytest.raises(ValidationError):
            validate_not_empty("\n\t", "field")

    def test_none_raises(self):
        """None should raise (falsy check)."""
        with pytest.raises(ValidationError):
            validate_not_empty(None, "value")

    def test_valid_string_passes(self):
        """Non-empty string should pass through."""
        result = validate_not_empty("hello", "greeting")
        assert result == "hello"

    def test_valid_string_stripped(self):
        """String with surrounding whitespace is stripped."""
        result = validate_not_empty("  hello world  ", "text")
        assert result == "hello world"

    def test_single_char_passes(self):
        """Single character passes."""
        result = validate_not_empty("x", "char")
        assert result == "x"

    def test_chinese_text_passes(self):
        """Chinese text passes validation."""
        result = validate_not_empty("你好世界", "中文名")
        assert result == "你好世界"


class TestValidateLength:
    """Test validate_length function."""

    def test_within_limit_passes(self):
        """String within max length passes."""
        result = validate_length("hello", "text", max_len=100)
        assert result == "hello"

    def test_exceeds_limit_truncates(self):
        """String exceeding max length is truncated, not rejected."""
        result = validate_length("abcdefghij", "text", max_len=5)
        assert result == "abcde"
        assert len(result) == 5

    def test_default_max_length(self):
        """Default max length is 50000."""
        long_string = "x" * 50000
        result = validate_length(long_string, "data")
        assert result == long_string

    def test_exactly_at_limit_passes(self):
        """String exactly at max length passes."""
        s = "abcde"
        result = validate_length(s, "text", max_len=5)
        assert result == s


class TestValidateEnum:
    """Test validate_enum function."""

    def test_valid_value_passes(self):
        """Value in allowed list passes through."""
        result = validate_enum("field_alias", "category", ALLOWED_CATEGORIES)
        assert result == "field_alias"

    def test_invalid_value_raises(self):
        """Value not in allowed list raises ValidationError."""
        with pytest.raises(ValidationError, match="必须在"):
            validate_enum("invalid_cat", "category", ALLOWED_CATEGORIES)

    def test_all_category_values(self):
        """All ALLOWED_CATEGORIES pass."""
        for cat in ALLOWED_CATEGORIES:
            result = validate_enum(cat, "category", ALLOWED_CATEGORIES)
            assert result == cat

    def test_all_severity_values(self):
        """All ALLOWED_SEVERITIES pass."""
        for sev in ALLOWED_SEVERITIES:
            result = validate_enum(sev, "severity", ALLOWED_SEVERITIES)
            assert result == sev

    def test_all_entity_types(self):
        """All ALLOWED_ENTITY_TYPES pass."""
        for etype in ALLOWED_ENTITY_TYPES:
            result = validate_enum(etype, "type", ALLOWED_ENTITY_TYPES)
            assert result == etype

    def test_all_scopes(self):
        """All ALLOWED_SCOPES pass."""
        for scope in ALLOWED_SCOPES:
            result = validate_enum(scope, "scope", ALLOWED_SCOPES)
            assert result == scope

    def test_all_relations(self):
        """All ALLOWED_RELATIONS pass."""
        for rel in ALLOWED_RELATIONS:
            result = validate_enum(rel, "relation", ALLOWED_RELATIONS)
            assert result == rel

    def test_empty_string_raises(self):
        """Empty string is not in any allowed list."""
        with pytest.raises(ValidationError):
            validate_enum("", "field", ALLOWED_CATEGORIES)

    def test_case_sensitive(self):
        """Validation is case-sensitive."""
        with pytest.raises(ValidationError):
            validate_enum("Field_Alias", "category", ALLOWED_CATEGORIES)


class TestValidateIntRange:
    """Test validate_int_range function."""

    def test_within_range_passes(self):
        """Value within range passes."""
        result = validate_int_range(5, "count", min_val=1, max_val=10)
        assert result == 5

    def test_below_min_raises(self):
        """Value below min raises ValidationError."""
        with pytest.raises(ValidationError, match="必须在 1-100 之间"):
            validate_int_range(-1, "count")

    def test_above_max_raises(self):
        """Value above max raises."""
        with pytest.raises(ValidationError, match="必须在 1-100 之间"):
            validate_int_range(101, "count")

    def test_at_min_passes(self):
        """Value exactly at min passes."""
        result = validate_int_range(1, "count", min_val=1, max_val=100)
        assert result == 1

    def test_at_max_passes(self):
        """Value exactly at max passes."""
        result = validate_int_range(100, "count", min_val=1, max_val=100)
        assert result == 100

    def test_custom_range(self):
        """Custom min/max range."""
        result = validate_int_range(50, "pct", min_val=0, max_val=100)
        assert result == 50

    def test_zero_with_custom_min(self):
        """Zero passes when min is 0."""
        result = validate_int_range(0, "index", min_val=0, max_val=99)
        assert result == 0

    def test_default_range(self):
        """Default range is 1-100."""
        result = validate_int_range(42, "answer")
        assert result == 42


class TestValidationError:
    """Test ValidationError class."""

    def test_is_value_error_subclass(self):
        """ValidationError is a subclass of ValueError."""
        assert issubclass(ValidationError, ValueError)

    def test_can_be_caught_as_value_error(self):
        """ValidationError can be caught as ValueError."""
        try:
            raise ValidationError("test error")
        except ValueError:
            pass  # expected
        else:
            pytest.fail("ValidationError should be caught as ValueError")

    def test_message_preserved(self):
        """Error message is preserved."""
        with pytest.raises(ValidationError, match="custom message 123"):
            raise ValidationError("custom message 123")


class TestAllowedConstants:
    """Verify the predefined allowed value lists."""

    def test_allowed_categories_not_empty(self):
        assert len(ALLOWED_CATEGORIES) > 0
        assert "field_alias" in ALLOWED_CATEGORIES

    def test_allowed_severities_not_empty(self):
        assert len(ALLOWED_SEVERITIES) > 0
        assert "critical" in ALLOWED_SEVERITIES

    def test_allowed_error_categories_not_empty(self):
        assert len(ALLOWED_ERROR_CATEGORIES) > 0
        assert "field_selection" in ALLOWED_ERROR_CATEGORIES

    def test_allowed_entity_types_not_empty(self):
        assert len(ALLOWED_ENTITY_TYPES) > 0
        assert "person" in ALLOWED_ENTITY_TYPES

    def test_allowed_scopes_not_empty(self):
        assert len(ALLOWED_SCOPES) > 0
        assert "personal" in ALLOWED_SCOPES

    def test_allowed_relations_not_empty(self):
        assert len(ALLOWED_RELATIONS) > 0
        assert "belongs_to" in ALLOWED_RELATIONS

    def test_allowed_source_types_not_empty(self):
        assert len(ALLOWED_SOURCE_TYPES) > 0
        assert "manual" in ALLOWED_SOURCE_TYPES

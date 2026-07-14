"""tests/test_version_compare.py"""
from app.core.version_compare import compare_versions, parse_version


def test_parse_version_valid():
    assert parse_version("1.10.2") == (1, 10, 2)


def test_parse_version_invalid_formats():
    assert parse_version("latest") is None
    assert parse_version("v1.0.0") is None
    assert parse_version("1.0") is None


def test_compare_versions_numeric_not_lexicographic():
    assert compare_versions("1.10.0", "1.9.0") == 1
    assert compare_versions("1.9.0", "1.10.0") == -1


def test_compare_versions_equal():
    assert compare_versions("1.0.0", "1.0.0") == 0


def test_compare_versions_invalid_returns_none():
    assert compare_versions("bad", "1.0.0") is None
    assert compare_versions("1.0.0", "bad") is None

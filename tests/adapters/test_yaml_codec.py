"""Tests for adapters.yaml_codec — the vendored PyYAML read as text and written in block style."""

from __future__ import annotations

import pytest

from adapters.yaml_codec import YamlCodecAdapter


def test_scalars_stay_text():
    doc = YamlCodecAdapter().load("a: 01.00\nb: true\nc: [1, 2]\nd: &x 5\ne: *x\n")
    assert doc == {"a": "01.00", "b": "true", "c": ["1", "2"], "d": "5", "e": "5"}


def test_dump_keeps_order_and_quotes_ambiguous_text():
    text = YamlCodecAdapter().dump({"z": {"01.04": {"Enabled": True}}, "a": 1})
    assert text.index("z:") < text.index("a:")
    assert "'01.04':" in text
    assert "Enabled: true" in text


def test_bad_yaml_is_a_value_error():
    with pytest.raises(ValueError, match="not readable YAML"):
        YamlCodecAdapter().load("a: [unclosed\n")

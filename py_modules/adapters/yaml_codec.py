"""YAML over the vendored pure-Python PyYAML. Implements ``YamlCodec``.

Reading uses PyYAML's ``BaseLoader``, which resolves no scalar types: every
value stays the text it was written as, so a version like ``01.00`` is never
turned into the number ``1.0`` (RPCS3's yaml-cpp reads scalars as text too).
Writing uses the safe dumper in block style with the keys in their given
order. The C accelerator is not shipped; the pure-Python parser is.
"""

from __future__ import annotations

from _vendor import yaml


class YamlCodecAdapter:
    """Real ``YamlCodec``."""

    def load(self, text: str) -> object:
        try:
            return yaml.load(text, Loader=yaml.BaseLoader)
        except yaml.YAMLError as exc:
            raise ValueError(f"not readable YAML: {exc}") from exc

    def dump(self, document: object) -> str:
        return yaml.safe_dump(document, default_flow_style=False, sort_keys=False, allow_unicode=True, width=1_000_000)

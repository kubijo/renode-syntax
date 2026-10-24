"""Typed source pins and derived facts shared by extraction and rendering."""

from typing import Literal

import msgspec


class Pin(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    repository: str
    revision: str
    paths: tuple[str, ...]


class Pins(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    renode: Pin
    infrastructure: Pin


class Location(msgspec.Struct, frozen=True):
    repository: Literal['renode', 'infrastructure']
    path: str
    line: int


class SourceFile(msgspec.Struct, frozen=True):
    repository: Literal['renode', 'infrastructure']
    path: str
    sha256: str


class Keyword(msgspec.Struct, frozen=True):
    name: str
    symbol: str
    source: Location


class Command(msgspec.Struct, frozen=True):
    name: str
    registration: Literal['base-constructor', 'monitor-registration', 'python-function']
    symbol: str
    source: Location
    definition: Location | None = None


class TokenRule(msgspec.Struct, frozen=True):
    order: int
    kind: str
    dotnet: str
    options: tuple[str, ...]
    sublime: str
    javascript: str
    source: Location
    javascript_flags: Literal['u'] = 'u'


class LexicalRule(msgspec.Struct, frozen=True):
    pattern: str
    source: Location


class RenodeData(msgspec.Struct, frozen=True):
    schema_version: int
    pins: Pins
    sources: tuple[SourceFile, ...]
    commands: tuple[Command, ...]
    keywords: tuple[Keyword, ...]
    tokenizer: tuple[TokenRule, ...]
    platform: dict[str, LexicalRule]


class SourceError(ValueError):
    """An upstream source form cannot be interpreted without a review."""

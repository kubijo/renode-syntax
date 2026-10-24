"""Read C# syntax trees and decode a deliberately bounded constant-expression subset."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from string import hexdigits
from typing import Literal, Protocol, cast

import tree_sitter_c_sharp
from renode_model import Location, SourceError
from tree_sitter import Language, Node, Parser, Tree


def walk(node: Node, kind: str | None = None) -> Iterator[Node]:
    if kind is None or node.type == kind:
        yield node
    for child in node.named_children:
        yield from walk(child, kind)


def text(node: Node) -> str:
    value = node.text
    if value is None:
        raise SourceError('A detached C# node has no source text')
    return value.decode('utf-8')


def field(node: Node, name: str) -> Node:
    result = node.child_by_field_name(name)
    if result is None:
        raise SourceError(f'Expected {name} on {node.type}: {text(node)[:120]}')
    return result


def arguments(node: Node) -> tuple[Node, ...]:
    result: list[Node] = []
    argument_list = next((child for child in node.named_children if child.type == 'argument_list'), None)
    if argument_list is None:
        raise SourceError(f'Expected arguments on {node.type}: {text(node)[:120]}')
    for argument in argument_list.named_children:
        if argument.type == 'comment':
            continue
        expressions = [child for child in argument.children if child.is_named or child.type in ('this', 'base')]
        if (
            argument.type != 'argument'
            or len(expressions) != 1
            or any(child.type in ('ref', 'out', 'in', ':') for child in argument.children)
        ):
            raise SourceError(f'Unsupported named/ref C# argument: {text(argument)}')
        result.append(expressions[0])
    return tuple(result)


def method(node: Node) -> str:
    function = field(node, 'function')
    if function.type in ('identifier', 'generic_name'):
        return text(function).split('<', 1)[0]
    if function.type == 'member_access_expression':
        return text(field(function, 'name')).split('<', 1)[0]
    raise SourceError(f'Unsupported C# invocation target: {text(function)}')


def literal(node: Node) -> str:
    value = text(node)
    if node.type == 'verbatim_string_literal':
        if not value.startswith('@"') or not value.endswith('"'):
            raise SourceError(f'Malformed verbatim C# literal: {value}')
        return value[2:-1].replace('""', '"')
    if node.type not in ('string_literal', 'character_literal'):
        raise SourceError(f'Expected a C# string/character constant, got {node.type}: {value}')
    quote = '"' if node.type == 'string_literal' else "'"
    if not value.startswith(quote) or not value.endswith(quote):
        raise SourceError(f'Unsupported C# string syntax: {value}')
    source = value[1:-1]
    result: list[str] = []
    index = 0
    escapes = {
        '0': '\0',
        'a': '\a',
        'b': '\b',
        'f': '\f',
        'n': '\n',
        'r': '\r',
        't': '\t',
        'v': '\v',
        "'": "'",
        '"': '"',
        '\\': '\\',
    }
    while index < len(source):
        char = source[index]
        index += 1
        if char != '\\':
            result.append(char)
            continue
        if index == len(source):
            raise SourceError('Truncated C# escape')
        code = source[index]
        index += 1
        if code in escapes:
            result.append(escapes[code])
        elif code in ('u', 'U', 'x'):
            maximum = {'u': 4, 'U': 8, 'x': 4}[code]
            start = index
            while index < len(source) and index - start < maximum and source[index] in hexdigits:
                index += 1
            if index == start or (code != 'x' and index - start != maximum):
                raise SourceError('Invalid C# Unicode escape')
            result.append(chr(int(source[start:index], 16)))
        else:
            raise SourceError(f'Unsupported C# escape \\{code}')
    decoded = ''.join(result)
    if node.type == 'character_literal' and len(decoded) != 1:
        raise SourceError('C# character literal must decode to one character')
    return decoded


@dataclass(frozen=True)
class Document:
    repository: Literal['renode', 'infrastructure']
    path: str
    root: Node

    def location(self, node: Node) -> Location:
        return Location(self.repository, self.path, node.start_point.row + 1)


class ByteParser(Protocol):
    # tree-sitter 0.26's removed ByteString annotation is unresolved on Python 3.15. Bind only
    # the bytes overload used here; keep the rest of the upstream Node/Tree typing.
    def parse(self, source: bytes, /) -> Tree: ...


def parse(repository: Literal['renode', 'infrastructure'], path: str, source: bytes) -> Document:
    parser = Parser(Language(tree_sitter_c_sharp.language()))
    root = cast(ByteParser, parser).parse(source).root_node
    if root.has_error:
        problem = next((node for node in walk(root) if node.type == 'ERROR' or node.is_missing), root)
        raise SourceError(f'{repository}:{path}:{problem.start_point.row + 1}: C# parse error: {text(problem)[:100]}')
    return Document(repository, path, root)


def load(repository: Literal['renode', 'infrastructure'], directory: Path, path: str) -> Document:
    return parse(repository, path, (directory / path).read_bytes())


def fields(node: Node) -> dict[str, Node]:
    result: dict[str, Node] = {}
    body = field(node, 'body')
    for declaration in body.named_children:
        if declaration.type != 'field_declaration':
            continue
        variable_list = next(child for child in declaration.named_children if child.type == 'variable_declaration')
        for variable in variable_list.named_children:
            if variable.type == 'variable_declarator':
                name = text(field(variable, 'name'))
                values = [child for child in variable.named_children if child != field(variable, 'name')]
                if len(values) != 1:
                    raise SourceError(f'Field {name} has no unique initializer')
                result[name] = values[0]
    return result

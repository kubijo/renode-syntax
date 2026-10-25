"""Derive platform lexer facts and scanner configuration from parsed upstream sources."""

import re
from pathlib import Path

import csharp_source
import msgspec
import upstream
from csharp_source import Document, arguments, field, fields, literal, method, text, walk
from extract_platform import Platform
from renode_model import Keyword, LexicalRule, Location, RenodeData, SourceError
from tree_sitter import Node


class StringFact(msgspec.Struct, frozen=True):
    value: str
    source: Location


class IntegerFact(msgspec.Struct, frozen=True):
    value: int
    source: Location


class ReplLexicon(msgspec.Struct, frozen=True):
    keywords: dict[str, Keyword]
    symbols: dict[str, StringFact]
    rules: dict[str, LexicalRule]
    indent: IntegerFact
    quote: StringFact
    multiquote: StringFact
    escape: StringFact
    line_comment: StringFact
    block_start: StringFact
    block_end: StringFact
    monitor_suffix: LexicalRule


def parser_literal(document: Document, node: Node, name: str) -> StringFact:
    calls = [item for item in walk(node, 'invocation_expression') if method(item) in ('Char', 'String')]
    values = [arguments(item)[0] for item in calls if len(arguments(item)) == 1]
    if len(values) != 1:
        raise SourceError(f'{name}: expected one literal Parse.Char/String')
    return StringFact(literal(values[0]), document.location(values[0]))


def identifier_pattern(keywords: tuple[str, ...]) -> str:
    # Subtract the finite keyword trie from the Unicode identifier language. This
    # avoids lookahead, and keeps reserved words excluded even in identifier-only states.
    def branch(prefix: str, candidates: tuple[str, ...]) -> str:
        children = sorted({word[len(prefix)] for word in candidates if len(word) > len(prefix)})
        excluded = re.escape(''.join(children))
        character = r'[^\P{L}' + excluded + ']'
        if prefix:
            character = r'[^\P{L}' + excluded + r']|[^\P{Nd}' + excluded + ']'
            if '_' not in children:
                character += '|_'
            character = '(?:' + character + ')'
        alternatives = [character + r'[\p{L}\p{Nd}_]*']
        if prefix and prefix not in candidates:
            alternatives.append('')
        for char in children:
            words = tuple(word for word in candidates if word.startswith(prefix + char))
            alternatives.append(re.escape(char) + branch(prefix + char, words))
        return '(?:' + '|'.join(alternatives) + ')'

    return branch('', keywords)


def prelexer(document: Document) -> tuple[IntegerFact, dict[str, StringFact]]:
    classes = [node for node in walk(document.root, 'class_declaration') if text(field(node, 'name')) == 'PreLexer']
    if len(classes) != 1:
        raise SourceError('Expected one PreLexer class')
    constants = fields(classes[0])
    indent = constants['SpacesPerIndent']
    if indent.type != 'integer_literal' or not text(indent).isdecimal() or int(text(indent)) <= 0:
        raise SourceError('SpacesPerIndent must be a positive integer literal')
    result = {
        name: StringFact(literal(constants[name]), document.location(constants[name]))
        for name in ('StringDelimiter', 'MultilineStringDelimiter')
    }
    methods = {text(field(node, 'name')): node for node in walk(classes[0], 'method_declaration')}
    sections = [
        node
        for node in walk(methods['FindInLine'], 'switch_section')
        if any(literal(child) == '/' for child in walk(node.named_children[0], 'character_literal'))
    ]
    if len(sections) != 1:
        raise SourceError('FindInLine: unsupported comment switch')
    comparisons = [
        node
        for node in walk(sections[0], 'binary_expression')
        if text(field(node, 'left')) == 'nextChar' and text(field(node, 'operator')) == '=='
    ]
    chars = {literal(field(node, 'right')): node for node in comparisons}
    if len(chars) != 2 or '/' not in chars:
        raise SourceError('FindInLine: unsupported comment delimiter comparisons')
    star = next(value for value in chars if value != '/')
    slash = literal(next(walk(sections[0].named_children[0], 'character_literal')))
    result['LineComment'] = StringFact(slash + slash, document.location(chars[slash]))
    result['BlockStart'] = StringFact(slash + star, document.location(chars[star]))
    endings = [
        arguments(node)[0]
        for node in walk(methods['HandleComments'], 'invocation_expression')
        if method(node) == 'IndexOf' and arguments(node) and arguments(node)[0].type == 'string_literal'
    ]
    if not endings or {literal(node) for node in endings} != {star + '/'}:
        raise SourceError('HandleComments: unsupported block comment terminator')
    result['BlockEnd'] = StringFact(literal(endings[0]), document.location(endings[0]))
    return IntegerFact(int(text(indent)), document.location(indent)), result


def lexicon(root: Path, data: RenodeData) -> ReplLexicon:
    directory = upstream.directory(root, 'renode')
    grammar = csharp_source.load('renode', directory, 'src/Renode/PlatformDescription/Syntax/Grammar.cs')
    platform = Platform(grammar, unicode=True)
    names = (
        'Separator',
        'AtSign',
        'MultiplexSign',
        'Colon',
        'Comma',
        'PlusSign',
        'OpeningChevron',
        'ClosingChevron',
        'OpeningBrace',
        'ClosingBrace',
        'OpeningSquareBracket',
        'ClosingSquareBracket',
        'Minus',
    )
    symbols = {name: parser_literal(grammar, platform.fields[name], name) for name in names}
    symbols['Dot'] = parser_literal(grammar, platform.fields['TypeName'], 'TypeName')
    symbols['Hash'] = parser_literal(grammar, platform.fields['IrqReceiver'], 'IrqReceiver')
    symbols['RightArrow'] = parser_literal(grammar, platform.fields['RightArrow'], 'RightArrow')
    symbols['EscapeCharacter'] = parser_literal(grammar, platform.fields['EscapeCharacter'], 'EscapeCharacter')
    rules = platform.lexical_rules()
    rules['Identifier'] = LexicalRule(
        identifier_pattern(tuple(item.name for item in data.keywords)), grammar.location(platform.fields['Identifier'])
    )
    indent, settings = prelexer(csharp_source.load('renode', directory, 'src/Renode/PlatformDescription/PreLexer.cs'))
    quote, multi = settings['StringDelimiter'], settings['MultilineStringDelimiter']
    if len(quote.value) != 1 or len(set(multi.value)) != 1:
        raise SourceError('Scanner requires one-character quotes and a repeated multiline delimiter')
    return ReplLexicon(
        {item.symbol: item for item in data.keywords},
        symbols,
        rules,
        indent,
        quote,
        multi,
        symbols['EscapeCharacter'],
        settings['LineComment'],
        settings['BlockStart'],
        settings['BlockEnd'],
        rules['MonitorSuffix'],
    )


def scanner_header(data: ReplLexicon) -> bytes:
    constants = {
        'INDENT_WIDTH': data.indent.value,
        'QUOTE': ord(data.quote.value),
        'MULTI_QUOTE': ord(data.multiquote.value[0]),
        'MULTI_WIDTH': len(data.multiquote.value),
        'ESCAPE': ord(data.escape.value),
        'SLASH': ord(data.line_comment.value[0]),
        'STAR': ord(data.block_start.value[1]),
    }
    constants.update({
        name: ord(data.symbols[symbol].value)
        for name, symbol in (
            ('OPEN_BRACE', 'OpeningBrace'),
            ('CLOSE_BRACE', 'ClosingBrace'),
            ('SEPARATOR', 'Separator'),
        )
    })
    return (
        '/* Generated from pinned Renode lexer facts. */\n'
        + ''.join(f'#define REPL_{name} {value}\n' for name, value in constants.items())
    ).encode()


def products(root: Path, data: RenodeData) -> dict[str, bytes]:
    result = lexicon(root, data)

    def quoted(value: str) -> str:
        return msgspec.json.encode(value).decode()

    keywords = '\n'.join(
        '  ' + quoted(result.keywords[symbol].name)
        for symbol in ('UsingKeyword', 'NewKeyword', 'AsKeyword', 'LocalKeyword')
    )
    punctuation = '\n'.join(
        '  ' + quoted(result.symbols[symbol].value)
        for symbol in ('Colon', 'Comma', 'Dot', 'AtSign', 'Hash', 'RightArrow', 'MultiplexSign', 'Minus', 'PlusSign')
    )
    template = (root / 'infra/templates/repl-highlights.scm.in').read_text()
    # Pair captures must belong to the same match, including zero-width layout blocks.
    brackets = '((block_start) @open (block_end) @close)\n'
    for opening, closing in (('OpeningSquareBracket', 'ClosingSquareBracket'), ('OpeningChevron', 'ClosingChevron')):
        brackets += (
            '('
            + quoted(result.symbols[opening].value)
            + ' @open '
            + quoted(result.symbols[closing].value)
            + ' @close)\n'
        )
    brackets += '(string ' + quoted(result.quote.value) + ' @open (string_end) @close)\n'
    brackets += '(multiline_string ' + quoted(result.multiquote.value) + ' @open (multiline_end) @close)\n'
    return {
        'generated/repl.json': msgspec.json.format(msgspec.json.encode(result), indent=2) + b'\n',
        'integrations/zed/languages/repl/highlights.scm': (
            template + '\n[\n' + keywords + '\n] @keyword\n\n[\n' + punctuation + '\n] @punctuation.delimiter\n'
        ).encode(),
        'integrations/zed/languages/repl/brackets.scm': brackets.encode(),
    }

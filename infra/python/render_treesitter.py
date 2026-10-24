"""Derive the Rust-regex subset and delimiters consumed by the monitor grammar."""

from pathlib import Path

import msgspec
from regex_source import SPACE, Regex, RegexParser
from renode_model import Location, RenodeData, SourceError


class Pattern(msgspec.Struct, frozen=True):
    pattern: str
    priority: int
    source: Location


class Lexicon(msgspec.Struct, frozen=True):
    rules: dict[str, tuple[Pattern, ...]]
    commands: tuple[str, ...]
    multiline_delimiter: str
    multiline_content: str
    execution_delimiter: str
    execution_content: str
    inline_space: str
    path_suffix: str


def rust_pattern(tree: Regex, singleline: bool = False) -> str:
    """Reject non-regular assertions and matching policies absent from Tree-sitter."""
    if tree.kind in ('negative', 'positive') or (
        tree.kind == 'repeat' and tree.value.endswith('?') and tree.value != '?'
    ):
        raise SourceError('Tree-sitter requires an explicit rewrite for assertions and lazy repetition')
    if tree.kind == 'dot' and singleline:
        return r'(?s:.)'
    inner = tuple(rust_pattern(child, singleline) for child in tree.children)
    if tree.kind == 'sequence':
        return ''.join(inner)
    if tree.kind == 'alternative':
        return '|'.join(inner)
    if tree.kind == 'group':
        return '(?:' + inner[0] + ')'
    if tree.kind == 'repeat':
        return inner[0] + tree.value
    # Rust supports Unicode categories but spells code points with braces.
    return tree.render('javascript').replace(r'\u0085', r'\x{85}')


def framed(tree: Regex) -> tuple[str, Regex]:
    children = tree.children
    leading = 0
    while leading < len(children) and children[leading].kind == 'literal':
        leading += 1
    start = children[:leading]
    if not start or children[-leading:] != start or len(children) != leading * 2 + 1:
        raise SourceError('Expected a symmetric literal delimiter around a repeated body')
    return ''.join(child.value for child in start), children[leading]


def content_pattern(delimiter: str) -> str:
    if not delimiter or len(set(delimiter)) != 1:
        raise SourceError('The bounded delimiter rewrite requires one repeated character')
    char = delimiter[0]
    escaped = Regex('literal', char).render()
    nonquote = '[^' + escaped + ']'
    return '(?:' + '|'.join(escaped * count + nonquote for count in range(len(delimiter))) + ')+'


def lexicon(data: RenodeData) -> Lexicon:
    rules: dict[str, tuple[Pattern, ...]] = {}
    multiline = execution = ''
    for rule in data.tokenizer:
        tree = RegexParser(rule.dotnet).parse()
        if rule.kind in ('MultilineStringToken', 'ExecutionToken'):
            delimiter, body = framed(tree)
            expected = '+?' if rule.kind == 'MultilineStringToken' else '*?'
            if body != Regex('repeat', expected, (Regex('dot'),)):
                raise SourceError(f'{rule.kind}: unexpected delimited body')
            if rule.kind == 'MultilineStringToken':
                if rule.options != ('Singleline',):
                    raise SourceError('MultilineStringToken: expected Singleline')
                multiline = delimiter
                marker = Regex('literal', delimiter[0]).render() * len(delimiter)
                pattern = marker + '(?s:.)' + content_pattern(delimiter)[:-1] + '*' + marker
            else:
                if rule.options or len(delimiter) != 1:
                    raise SourceError('ExecutionToken: expected one delimiter and no flags')
                execution = delimiter
                pattern = Regex('literal', delimiter).render() + '[^' + delimiter + r'\n]*' + delimiter
        elif rule.kind == 'PathToken':
            # (?!;) applies to every repetition, including the escaped-space alternative.
            expected_tree = RegexParser(r'^\@(?:(?!;)((\\ )|\S))+').parse()
            if tree != expected_tree:
                raise SourceError('PathToken: the lookahead rewrite needs review')
            pattern = '@(?:\\\\ |[^' + SPACE.replace(r'\u0085', r'\x{85}') + ';])+'
        else:
            pattern = rust_pattern(tree, 'Singleline' in rule.options)
        rules[rule.kind] = (*rules.get(rule.kind, ()), Pattern(pattern, len(data.tokenizer) - rule.order, rule.source))
    if not multiline or not execution:
        raise SourceError('Missing multiline or execution token')
    terminator = rules['MultilineStringTerminatorToken'][0].pattern
    if terminator != multiline:
        raise SourceError('Multiline token and terminator disagree')
    whitespace = rules['Whitespace'][0].pattern
    if whitespace != '[' + SPACE.replace(r'\u0085', r'\x{85}') + ']+':
        raise SourceError('WhitespaceToken rewrite needs review')
    return Lexicon(
        rules,
        tuple(command.name for command in data.commands),
        multiline,
        content_pattern(multiline),
        execution,
        '[^' + execution + r'\n]+',
        r'[\p{Z}\t\v\f\x{85}]+',
        '/' + rules['PathToken'][0].pattern[1:],
    )


def products(root: Path, data: RenodeData) -> dict[str, bytes]:
    names = '\n'.join('    ' + msgspec.json.encode(command.name).decode() for command in data.commands)
    template = (root / 'infra/templates/resc-highlights.scm.in').read_text()
    builtins = '\n((command name: (literal) @keyword)\n  (#any-of? @keyword\n' + names + '))\n'
    return {
        'generated/resc.json': msgspec.json.format(msgspec.json.encode(lexicon(data)), indent=2) + b'\n',
        'zed/languages/resc/highlights.scm': (template + builtins).encode(),
    }

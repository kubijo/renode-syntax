"""Combine source-derived lexical facts with hand-maintained Sublime contexts."""

import re
from pathlib import Path

import msgspec
from regex_source import Regex, RegexParser
from renode_model import RenodeData, SourceError


def edges(tree: Regex) -> tuple[str, str]:
    children = tree.children if tree.kind == 'sequence' else (tree,)
    leading: list[str] = []
    trailing: list[str] = []
    for child in children:
        if child.kind != 'literal':
            break
        leading.append(child.render())
    for child in reversed(children):
        if child.kind != 'literal':
            break
        trailing.append(child.render())
    if not leading:
        raise SourceError('A structured token must have a literal opening delimiter')
    return ''.join(leading), ''.join(reversed(trailing))


def escapes(tree: Regex) -> tuple[str, ...]:
    result: tuple[str, ...] = ()
    if tree.kind == 'sequence' and len(tree.children) >= 2:
        first, second = tree.children[:2]
        if first.kind == 'literal' and first.value == '\\' and second.kind == 'dot':
            result += (first.render() + second.render(),)
    for child in tree.children:
        result += escapes(child)
    return result


def builtin_lines(data: RenodeData) -> str:
    names = [item.name for item in data.commands if item.registration != 'python-function']
    names += [item.name for item in data.commands if item.registration == 'python-function']
    lines: list[str] = []
    current = '      '
    for name in names:
        item = ('|' if current != '      ' or lines else '') + re.escape(name)
        if len(current) + len(item) > 92:
            lines.append(current)
            current = '      '
        current += item
    lines.append(current)
    return '\n'.join(lines)


def substitutions(data: RenodeData) -> dict[str, str]:
    result = {'BUILTINS': builtin_lines(data)}
    result.update({f'Command_{item.name}': re.escape(item.name) for item in data.commands})
    symbols = {item.symbol: item.name for item in data.keywords}
    for symbol, name in symbols.items():
        result[symbol] = re.escape(name)
    result['KEYWORDS'] = '|'.join(re.escape(item.name) for item in data.keywords)
    for name, rule in data.platform.items():
        result[name] = rule.pattern
    by_kind: dict[str, list[str]] = {}
    for rule in data.tokenizer:
        by_kind.setdefault(rule.kind, []).append(rule.sublime)
    for kind, patterns in by_kind.items():
        for index, pattern in enumerate(patterns):
            result[f'{kind}_{index}'] = pattern
    framed = {
        'CommentToken',
        'ExecutionToken',
        'MultilineStringToken',
        'MultilineStringTerminatorToken',
        'StringToken',
    }
    counts: dict[str, int] = {}
    for rule in data.tokenizer:
        index = counts.get(rule.kind, 0)
        counts[rule.kind] = index + 1
        if rule.kind not in framed:
            continue
        tree = RegexParser(rule.dotnet).parse()
        start, end = edges(tree)
        prefix = f'{rule.kind}_{index}'
        result[prefix + '_START_yaml'] = msgspec.json.encode(start).decode()
        result[prefix + '_END_yaml'] = msgspec.json.encode(end).decode()
        if rule.kind == 'StringToken':
            escape_patterns = escapes(tree)
            if len(escape_patterns) != 1:
                raise SourceError('StringToken must have one escape sequence rule')
            result[prefix + '_ESCAPE_yaml'] = msgspec.json.encode(escape_patterns[0]).decode()
    if result['MultilineStringToken_0_START_yaml'] != result['MultilineStringTerminatorToken_0_START_yaml']:
        raise SourceError('Multiline token and terminator delimiters disagree')
    if result['StringToken_0_ESCAPE_yaml'] != result['StringToken_1_ESCAPE_yaml']:
        raise SourceError('Single/double quoted strings no longer share their escape rule')
    for kind, marker in (('PathToken', '@'), ('VariableToken', r'\$')):
        pattern = by_kind[kind][0]
        if not pattern.startswith(marker):
            raise SourceError(f'{kind}: expected a leading marker for Sublime capture 1')
        result[kind + '_captured'] = '(' + marker + ')' + pattern[len(marker) :]
    literal = next(rule for rule in data.tokenizer if rule.kind == 'LiteralToken')
    tree = RegexParser(literal.dotnet).parse()
    if (
        tree.kind != 'sequence'
        or len(tree.children) != 2
        or tree.children[1].kind != 'repeat'
        or tree.children[1].value != '*'
    ):
        raise SourceError('LiteralToken no longer has a start class followed by a continuation class')
    continuation = tree.children[1].children[0]
    if continuation.kind != 'class':
        raise SourceError('LiteralToken continuation must be a character class')
    result['LITERAL_END'] = '(?!' + continuation.render() + ')'
    return result


def render(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match[1]
        if key not in values:
            raise SourceError(f'Unknown template substitution: {key}')
        return values[key]

    result = re.sub(r'@@([A-Za-z0-9_]+)@@', replace, template)
    if '@@' in result:
        raise SourceError('Unexpanded template marker')
    return result


def grammars(root: Path, data: RenodeData) -> dict[str, bytes]:
    values = substitutions(data)
    templates = {
        name: (root / f'infra/templates/{name}.yaml.in').read_text() for name in ('RenodePlatform', 'RenodeScript')
    }
    keys = set(re.findall(r'@@([A-Za-z0-9_]+)@@', '\n'.join(templates.values())))
    counts: dict[str, int] = {}
    for rule in data.tokenizer:
        index = counts.get(rule.kind, 0)
        counts[rule.kind] = index + 1
        key = f'{rule.kind}_{index}'
        consumed = key in keys or any(item.startswith(key + '_') for item in keys)
        consumed = consumed or (index == 0 and rule.kind + '_captured' in keys)
        # Sublime consumes otherwise unmatched whitespace itself.
        if not consumed and (rule.kind != 'Whitespace' or index != 0):
            raise SourceError(f'The Sublime templates do not account for upstream token {key}')
    return {
        f'integrations/sublime/{name}.sublime-syntax': render(template, values).encode()
        for name, template in templates.items()
    }

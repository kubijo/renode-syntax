"""Parse and translate the bounded .NET regex language used by Renode's tokenizer.

Captures are intentionally discarded: token factories consume the whole match. Unsupported constructs
require an explicit review rather than passing an engine-specific expression to another consumer.
"""

from dataclasses import dataclass
from typing import Literal

from renode_model import SourceError

Consumer = Literal['sublime', 'javascript']
WORD = r'\p{L}\p{Mn}\p{Nd}\p{Pc}'
SPACE = r'\p{Z}\t\n\v\f\r\u0085'


@dataclass(frozen=True)
class Regex:
    kind: Literal[
        'literal', 'escape', 'class', 'dot', 'sequence', 'alternative', 'group', 'negative', 'positive', 'repeat'
    ]
    value: str = ''
    children: tuple[Regex, ...] = ()

    def render(self, consumer: Consumer = 'sublime', singleline: bool = False) -> str:
        inner = [child.render(consumer, singleline) for child in self.children]
        if self.kind == 'literal':
            return ('\\' if self.value in r'\.^$|?*+()[]{}' else '') + self.value
        if self.kind == 'escape':
            # JavaScript's \d and \w are ASCII; .NET's default classes are Unicode.
            if consumer == 'javascript' and self.value in 'dwDsSW':
                return {
                    'd': r'\p{Nd}',
                    'D': r'\P{Nd}',
                    'w': '[' + WORD + ']',
                    'W': '[^' + WORD + ']',
                    's': '[' + SPACE + ']',
                    'S': '[^' + SPACE + ']',
                }[self.value]
            return '\\' + self.value
        if self.kind == 'class':
            value = self.value
            if consumer == 'javascript':
                value = value.replace(r'\w', WORD).replace(r'\d', r'\p{Nd}').replace(r'\s', SPACE)
            return '[' + value + ']'
        if self.kind == 'dot':
            return r'[\s\S]' if singleline else (r'[^\n]' if consumer == 'javascript' else '.')
        if self.kind == 'sequence':
            return ''.join(inner)
        if self.kind == 'alternative':
            return '|'.join(inner)
        if self.kind == 'repeat':
            return inner[0] + self.value
        prefix = {'group': '?:', 'negative': '?!', 'positive': '?='}[self.kind]
        return '(' + prefix + inner[0] + ')'


class RegexParser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0

    def fail(self, reason: str) -> SourceError:
        return SourceError(f'Unsupported .NET regex at offset {self.index}: {reason}: {self.source!r}')

    def peek(self) -> str:
        return self.source[self.index : self.index + 1]

    def take(self) -> str:
        char = self.peek()
        if not char:
            raise self.fail('unexpected end')
        self.index += 1
        return char

    def parse(self) -> Regex:
        if self.take() != '^':
            raise self.fail('token rule must start at the current offset with ^')
        result = self.alternatives(False)
        if self.peek():
            raise self.fail('unmatched closing parenthesis')
        return result

    def alternatives(self, ignore_case: bool) -> Regex:
        choices = [self.sequence(ignore_case)]
        while self.peek() == '|':
            self.index += 1
            choices.append(self.sequence(ignore_case))
        return choices[0] if len(choices) == 1 else Regex('alternative', children=tuple(choices))

    def sequence(self, ignore_case: bool) -> Regex:
        children: list[Regex] = []
        while self.peek() and self.peek() not in ')|':
            atom = self.atom(ignore_case)
            repeat = ''
            if self.peek() and self.peek() in '*+?':
                repeat = self.take()
            elif self.peek() == '{':
                start = self.index
                self.index += 1
                while self.peek().isdigit() or self.peek() == ',':
                    self.index += 1
                if self.take() != '}':
                    raise self.fail('invalid counted repetition')
                repeat = self.source[start : self.index]
                limits = repeat[1:-1].split(',')
                if (
                    len(limits) > 2
                    or not limits[0].isdigit()
                    or (len(limits) == 2 and limits[1] and not limits[1].isdigit())
                ):
                    raise self.fail('invalid counted repetition')
                if len(limits) == 2 and limits[1] and int(limits[0]) > int(limits[1]):
                    raise self.fail('reversed repetition limits')
            if repeat:
                if self.peek() == '?':
                    repeat += self.take()
                atom = Regex('repeat', repeat, (atom,))
            children.append(atom)
        return children[0] if len(children) == 1 else Regex('sequence', children=tuple(children))

    def atom(self, ignore_case: bool) -> Regex:
        char = self.take()
        if char == '(':
            kind: Literal['group', 'negative', 'positive'] = 'group'
            scoped_case = ignore_case
            if self.peek() == '?':
                self.index += 1
                prefix = self.take()
                if prefix == 'i' and self.take() == ':':
                    scoped_case = True
                elif prefix in (':', '!', '='):
                    if prefix == '!':
                        kind = 'negative'
                    elif prefix == '=':
                        kind = 'positive'
                else:
                    raise self.fail('group/inline flag')
            child = self.alternatives(scoped_case)
            if self.take() != ')':
                raise self.fail('unterminated group')
            return Regex(kind, children=(child,))
        if char == '[':
            content = ''
            while self.peek() != ']':
                item = self.take()
                if item == '[':
                    raise self.fail('nested/subtracted character class')
                if item == '\\':
                    code = self.take()
                    if code not in r'dsw\.-?+[]^':
                        raise self.fail('character-class escape')
                    item += code
                content += item
            self.index += 1
            if not content or content == '^' or '-[' in content:
                raise self.fail('empty/subtracted character class')
            if ignore_case:
                if (
                    len(content) == 3
                    and content[1] == '-'
                    and content[0].isascii()
                    and content[0].islower()
                    and content[2].isascii()
                    and content[2].islower()
                ):
                    content += content.upper()
                elif content.isascii() and content.isalpha():
                    content += content.swapcase()
                else:
                    raise self.fail('case-insensitive character class')
            return Regex('class', content)
        if char == '\\':
            code = self.take()
            if code in 'dswDSWnrt':
                if ignore_case:
                    raise self.fail('case-insensitive escape')
                return Regex('escape', code)
            if code.isalnum():
                raise self.fail('backreference/property/unknown escape')
            return Regex('literal', code)
        if char == '.':
            return Regex('dot')
        if char in '^$*+?{}]':
            raise self.fail('anchor or unattached repetition')
        if ignore_case and char.isalpha():
            if not char.isascii():
                raise self.fail('Unicode case folding')
            return Regex('class', char.lower() + char.upper())
        return Regex('literal', char)


def translate(source: str, options: tuple[str, ...] = ()) -> tuple[str, str]:
    if any(option != 'Singleline' for option in options) or len(set(options)) != len(options):
        raise SourceError(f'Unsupported RegexOptions: {options}')
    parsed = RegexParser(source).parse()
    return parsed.render('sublime', 'Singleline' in options), parsed.render('javascript', 'Singleline' in options)

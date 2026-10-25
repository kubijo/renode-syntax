"""Extract keywords and a small lexical subset of Sprache, not the platform grammar's structure."""

import re

from csharp_source import Document, arguments, field, fields, literal, method, text, walk
from renode_model import Keyword, LexicalRule, SourceError
from tree_sitter import Node


class Platform:
    def __init__(self, document: Document, *, unicode: bool = False) -> None:
        self.document = document
        self.unicode = unicode
        declarations = [
            node for node in walk(document.root, 'class_declaration') if text(field(node, 'name')) == 'Grammar'
        ]
        if len(declarations) != 1:
            raise SourceError('Expected one platform Grammar class')
        self.fields = fields(declarations[0])
        self.pending: set[str] = set()

    def keywords(self) -> tuple[Keyword, ...]:
        result: list[Keyword] = []
        calls = tuple(
            node for node in walk(self.document.root, 'invocation_expression') if method(node) == 'MakeKeyword'
        )
        for symbol, value in self.fields.items():
            if value in calls:
                values = arguments(value)
                if len(values) not in (1, 2):
                    raise SourceError(f'Unsupported MakeKeyword overload: {text(value)}')
                result.append(Keyword(literal(values[0]), symbol, self.document.location(value)))
        if len(result) != len(calls) or not result or len({item.name for item in result}) != len(result):
            raise SourceError('MakeKeyword must declare unique, literal field initializers')
        return tuple(result)

    def rule(self, name: str) -> str:
        if name not in self.fields or name in self.pending:
            raise SourceError(f'Unknown or recursive platform lexical field: {name}')
        self.pending.add(name)
        try:
            return self.expression(self.fields[name])
        finally:
            self.pending.remove(name)

    def expression(self, node: Node) -> str:
        if node.type == 'identifier':
            return self.rule(text(node))
        if node.type == 'parenthesized_expression':
            return self.expression(node.named_children[0])
        if node.type == 'member_access_expression' and text(field(node, 'expression')) == 'Parse':
            # Preserve the migrated highlighter's ASCII identifier policy. This is a lexical
            # approximation; the full Sprache predicates and parser semantics are not transpiled.
            primitives = {'Letter': '[A-Za-z]', 'LetterOrDigit': '[A-Za-z0-9]', 'Number': r'\d+'}
            if self.unicode:
                primitives = {'Letter': r'\p{L}', 'LetterOrDigit': r'[\p{L}\p{Nd}]', 'Number': r'\p{Nd}+'}
            name = text(field(node, 'name'))
            if name not in primitives:
                raise SourceError(f'Unsupported Sprache primitive: {text(node)}')
            return primitives[name]
        if node.type == 'query_expression':
            clauses = node.named_children
            if (
                not clauses
                or clauses[-1].type != 'select_clause'
                or any(child.type != 'from_clause' for child in clauses[:-1])
            ):
                raise SourceError(f'Unsupported lexical query: {text(node)}')
            return ''.join(self.expression(clause.named_children[-1]) for clause in clauses[:-1])
        if node.type != 'invocation_expression':
            raise SourceError(f'Unsupported Sprache lexical expression: {text(node)}')
        function = field(node, 'function')
        if function.type != 'member_access_expression':
            raise SourceError(f'Unsupported lexical invocation: {text(node)}')
        receiver = field(function, 'expression')
        name = method(node)
        values = arguments(node)
        if text(receiver) == 'Parse' and name in ('Char', 'Chars', 'String'):
            if len(values) != 1:
                raise SourceError(f'Unsupported {name} overload')
            value = literal(values[0])
            return '[' + re.escape(value) + ']' if name == 'Chars' else re.escape(value)
        if name in ('Token', 'Text', 'Positioned', 'Once') and not values:
            return self.expression(receiver)
        if name == 'Named' and len(values) == 1:
            _ = literal(values[0])
            return self.expression(receiver)
        if name in ('Select', 'Then', 'Where') and len(values) == 1 and values[0].type == 'lambda_expression':
            body = field(values[0], 'body')
            if name == 'Then':
                return self.expression(receiver) + self.expression(body)
            if name == 'Where' and text(body) != '!Keywords.Contains(x)':
                raise SourceError(f'Unsupported lexical predicate: {text(body)}')
            # Select changes the value, not the characters consumed. Keyword exclusion is applied
            # by the template's keyword guard, separate from the identifier's lexical pattern.
            return self.expression(receiver)
        if name in ('Many', 'XMany', 'AtLeastOnce', 'Optional') and not values:
            suffix = {'Many': '*', 'XMany': '*', 'AtLeastOnce': '+', 'Optional': '?'}[name]
            return '(?:' + self.expression(receiver) + ')' + suffix
        if name in ('Or', 'XOr') and len(values) == 1:
            return '(?:' + self.expression(receiver) + '|' + self.expression(values[0]) + ')'
        raise SourceError(f'Unsupported Sprache lexical call: {text(node)}')

    def lexical_rules(self) -> dict[str, LexicalRule]:
        names = (
            'GeneralIdentifier',
            'TypeName',
            'HexadecimalUnsignedLong',
            'DecimalUnsignedLong',
            'HexadecimalNumberWithSign',
            'DecimalNumberWithSign',
            'Number',
            'RightArrow',
            'MultiplexSign',
            'AtSign',
            'Separator',
            'Comma',
            'Colon',
            'QuotationMark',
            'MultiQuotationMark',
            'EscapeCharacter',
        )
        result = {name: LexicalRule(self.rule(name), self.document.location(self.fields[name])) for name in names}
        decimal_queries = tuple(walk(self.fields['DecimalNumberWithSign'], 'query_expression'))
        if len(decimal_queries) != 1:
            raise SourceError('DecimalNumberWithSign must have one lexical query')
        clauses = [node for node in decimal_queries[0].named_children if node.type == 'from_clause']
        if len(clauses) != 3 or text(field(clauses[0], 'name')) != 'sign':
            raise SourceError('DecimalNumberWithSign must consume a sign followed by integer/fraction clauses')
        # Keep the consumer's word boundary between the sign and magnitude. It prevents numbers
        # inside identifiers from being highlighted, without excluding a leading minus.
        result['DecimalSign'] = LexicalRule(
            self.expression(clauses[0].named_children[-1]), self.document.location(clauses[0])
        )
        result['DecimalMagnitude'] = LexicalRule(
            ''.join(self.expression(node.named_children[-1]) for node in clauses[1:]),
            self.document.location(clauses[1]),
        )
        suffixes: list[tuple[str, Node]] = []
        for name in ('PreinitAttribute', 'InitAttribute', 'ResetAttribute'):
            if name not in self.fields:
                raise SourceError(f'Missing platform monitor block: {name}')
            predicates = [node for node in walk(self.fields[name], 'invocation_expression') if method(node) == 'Where']
            if len(predicates) != 1:
                raise SourceError(f'{name}: expected one block suffix predicate')
            values = arguments(predicates[0])
            if len(values) != 1 or values[0].type != 'lambda_expression':
                raise SourceError(f'{name}: unsupported suffix lambda')
            body = field(values[0], 'body')
            if (
                body.type != 'binary_expression'
                or text(field(body, 'left')) != 'x'
                or text(field(body, 'operator')) != '=='
            ):
                raise SourceError(f'{name}: unsupported suffix predicate')
            suffixes.append((literal(field(body, 'right')), predicates[0]))
        if len({value for value, _ in suffixes}) != 1:
            raise SourceError('Monitor block suffixes disagree')
        result['MonitorSuffix'] = LexicalRule(re.escape(suffixes[0][0]), self.document.location(suffixes[0][1]))
        return result

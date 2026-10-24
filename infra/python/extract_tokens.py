"""Read the ordered token factory registrations without scanning comments or strings."""

from csharp_source import Document, arguments, field, literal, method, text, walk
from regex_source import translate
from renode_model import SourceError, TokenRule


def tokenizer(document: Document) -> tuple[TokenRule, ...]:
    factories = [
        node for node in walk(document.root, 'method_declaration') if text(field(node, 'name')) == 'CreateTokenizer'
    ]
    if len(factories) != 1:
        raise SourceError('Expected one CreateTokenizer method')
    for statement in field(factories[0], 'body').named_children:
        if statement.type == 'comment':
            continue
        if statement.type == 'local_declaration_statement':
            variables = tuple(walk(statement, 'variable_declarator'))
            if len(variables) == 1 and text(field(variables[0], 'name')) == 'tokenizer':
                values = [child for child in variables[0].named_children if child != field(variables[0], 'name')]
                if (
                    len(values) == 1
                    and values[0].type == 'object_creation_expression'
                    and text(field(values[0], 'type')) == 'Tokenizer'
                    and not arguments(values[0])
                ):
                    continue
        if (
            statement.type == 'return_statement'
            and len(statement.named_children) == 1
            and text(statement.named_children[0]) == 'tokenizer'
        ):
            continue
        if statement.type == 'expression_statement' and len(statement.named_children) == 1:
            expression = statement.named_children[0]
            if (
                expression.type == 'invocation_expression'
                and text(field(expression, 'function')) == 'tokenizer.AddToken'
            ):
                continue
        raise SourceError(f'{document.location(statement)}: unsupported CreateTokenizer registration statement')
    result: list[TokenRule] = []
    for call in walk(factories[0], 'invocation_expression'):
        if method(call) != 'AddToken':
            continue
        function = field(call, 'function')
        if function.type != 'member_access_expression' or text(field(function, 'expression')) != 'tokenizer':
            raise SourceError('Unexpected AddToken receiver')
        values = arguments(call)
        if len(values) != 2:
            raise SourceError('AddToken requires a regex and a factory')
        regex, factory = values
        if regex.type != 'object_creation_expression' or text(field(regex, 'type')) != 'Regex':
            raise SourceError(f'Unsupported token regex construction: {text(regex)}')
        regex_arguments = arguments(regex)
        if len(regex_arguments) not in (1, 2):
            raise SourceError('Unsupported Regex constructor overload')
        pattern = literal(regex_arguments[0])
        options: tuple[str, ...] = ()
        if len(regex_arguments) == 2:
            option = regex_arguments[1]
            if option.type != 'member_access_expression' or text(field(option, 'expression')) != 'RegexOptions':
                raise SourceError(f'Unsupported regex option expression: {text(option)}')
            options = (text(field(option, 'name')),)
        if factory.type != 'lambda_expression' or text(field(factory, 'parameters')) != 'x':
            raise SourceError(f'Unsupported token factory: {text(factory)}')
        body = field(factory, 'body')
        if body.type == 'null_literal':
            kind = 'Whitespace'
        elif body.type == 'object_creation_expression' and [text(arg) for arg in arguments(body)] == ['x']:
            kind = text(field(body, 'type'))
        else:
            raise SourceError(f'Unsupported token factory body: {text(body)}')
        sublime, javascript = translate(pattern, options)
        result.append(TokenRule(len(result), kind, pattern, options, sublime, javascript, document.location(call)))
    if not result:
        raise SourceError('CreateTokenizer contains no rules')
    return tuple(result)

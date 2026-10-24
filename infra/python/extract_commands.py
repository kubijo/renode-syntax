"""Extract full command registrations from parsed C# and the default IronPython script."""

import ast
from dataclasses import dataclass

from csharp_source import Document, arguments, field, literal, method, text, walk
from fissix.refactor import RefactoringTool
from renode_model import Command, Location, SourceError
from tree_sitter import Node


@dataclass(frozen=True)
class Constructor:
    symbol: str
    source: Location
    name: str | None
    parameter: int | None


def command_name(value: str) -> str:
    if not value or not all(char.isascii() and (char.isalnum() or char == '_') for char in value):
        raise SourceError(f'Unsupported full command name: {value!r}')
    return value


def constructors(documents: tuple[Document, ...]) -> dict[str, Constructor]:
    result: dict[str, Constructor] = {}
    for document in documents:
        for declaration in walk(document.root, 'class_declaration'):
            bases = next((child for child in declaration.named_children if child.type == 'base_list'), None)
            if bases is None or not any(text(base) in ('Command', 'AutoLoadCommand') for base in bases.named_children):
                continue
            if any(child.type == 'modifier' and text(child) == 'abstract' for child in declaration.named_children):
                continue
            symbol = text(field(declaration, 'name'))
            body = field(declaration, 'body')
            constants: dict[str, Node] = {}
            for member in body.named_children:
                if member.type == 'field_declaration' and any(
                    text(child) == 'const' for child in member.named_children
                ):
                    for variable in walk(member, 'variable_declarator'):
                        values = [child for child in variable.named_children if child != field(variable, 'name')]
                        if len(values) != 1:
                            raise SourceError(f'{symbol}: unsupported constant declaration')
                        constants[text(field(variable, 'name'))] = values[0]
            definitions = [child for child in body.named_children if child.type == 'constructor_declaration']
            if len(definitions) != 1:
                raise SourceError(f'{symbol}: expected one command constructor')
            constructor = definitions[0]
            initializer = next(
                (child for child in constructor.named_children if child.type == 'constructor_initializer'), None
            )
            if initializer is None or not any(child.type == 'base' for child in initializer.children):
                raise SourceError(f'{symbol}: expected a base command registration')
            values = arguments(initializer)
            if len(values) < 3:
                raise SourceError(f'{symbol}: base registration lacks its name/description')
            name = values[1]
            parameter: int | None = None
            resolved: str | None = None
            if name.type == 'identifier' and text(name) not in constants:
                parameters = field(constructor, 'parameters').named_children
                names = [text(field(item, 'name')) for item in parameters if item.type == 'parameter']
                if text(name) not in names:
                    raise SourceError(f'{symbol}: unresolved command name {text(name)}')
                parameter = names.index(text(name))
            else:
                if name.type == 'identifier':
                    name = constants[text(name)]
                resolved = command_name(literal(name))
            if symbol in result:
                raise SourceError(f'Duplicate command class {symbol}')
            result[symbol] = Constructor(symbol, document.location(name), resolved, parameter)
    return result


def csharp_commands(documents: tuple[Document, ...], monitor: Document) -> tuple[Command, ...]:
    definitions = constructors(documents)
    result = [
        Command(item.name, 'base-constructor', item.symbol, item.source)
        for item in definitions.values()
        if item.name is not None
    ]
    initializers = [
        node for node in walk(monitor.root, 'method_declaration') if text(field(node, 'name')) == 'InitCommands'
    ]
    if len(initializers) != 1:
        raise SourceError('Monitor must have one InitCommands method')
    initializer = initializers[0]
    bindings: dict[str, Node] = {}
    registrations: set[Node] = set()
    for statement in field(initializer, 'body').named_children:
        if statement.type == 'comment':
            continue
        if statement.type == 'local_declaration_statement':
            for variable in walk(statement, 'variable_declarator'):
                values = [child for child in variable.named_children if child != field(variable, 'name')]
                if len(values) != 1 or values[0].type != 'object_creation_expression':
                    raise SourceError('InitCommands must bind command objects directly')
                bindings[text(field(variable, 'name'))] = values[0]
            continue
        if statement.type == 'expression_statement' and len(statement.named_children) == 1:
            call = statement.named_children[0]
            if call.type == 'invocation_expression' and text(field(call, 'function')) == 'Commands.Add':
                registrations.add(call)
                continue
        raise SourceError(f'{monitor.location(statement)}: unsupported InitCommands registration statement')
    used: set[str] = set()
    for call in walk(monitor.root, 'invocation_expression'):
        function = field(call, 'function')
        if (
            function.type != 'member_access_expression'
            or text(field(function, 'expression')) != 'Commands'
            or method(call) != 'Add'
        ):
            continue
        owner = call.parent
        while owner is not None and owner.type != 'method_declaration':
            owner = owner.parent
        if owner != initializer:
            # RegisterCommand is the runtime plug-in API, not a default command declaration.
            if (
                owner is not None
                and text(field(owner, 'name')) == 'RegisterCommand'
                and [text(arg) for arg in arguments(call)] == ['command']
            ):
                continue
            raise SourceError(f'{monitor.location(call)}: unrecognised command registration site')
        if call not in registrations:
            raise SourceError('InitCommands registrations must be unconditional top-level statements')
        values = arguments(call)
        if len(values) != 1:
            raise SourceError('Commands.Add must have one argument')
        creation = values[0]
        if creation.type == 'identifier':
            binding = bindings.get(text(creation))
            if binding is None or binding.start_byte > call.start_byte:
                raise SourceError(f'Unresolved registered command variable: {text(creation)}')
            creation = binding
        if creation.type != 'object_creation_expression':
            raise SourceError(f'Unsupported Commands.Add argument: {text(creation)}')
        symbol = text(field(creation, 'type'))
        definition = definitions.get(symbol)
        if definition is None:
            raise SourceError(f'Unknown registered command class: {symbol}')
        used.add(symbol)
        if definition.parameter is not None:
            actuals = arguments(creation)
            if definition.parameter >= len(actuals):
                raise SourceError(f'{symbol}: missing name argument')
            name = command_name(literal(actuals[definition.parameter]))
            result.append(Command(name, 'monitor-registration', symbol, monitor.location(creation), definition.source))
    unresolved = {item.symbol for item in definitions.values() if item.parameter is not None} - used
    if unresolved:
        raise SourceError(f'Uninstantiated parameterised command classes: {sorted(unresolved)}')
    return tuple(sorted(result, key=lambda item: item.name))


def python_commands(source: str, path: str = 'scripts/monitor.py') -> tuple[Command, ...]:
    # Renode executes this file with IronPython 2. Only print statements need normalization for ast.
    try:
        normalized = str(RefactoringTool(['fissix.fixes.fix_print']).refactor_string(source, path))
        module = ast.parse(normalized, filename=path)
    except Exception as error:
        raise SourceError(f'{path}: cannot parse the default monitor script: {error}') from error
    top_level = {node for node in module.body if isinstance(node, ast.FunctionDef)}
    result: list[Command] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id.startswith('mc_'):
            raise SourceError(f'{path}:{node.lineno}: unsupported assigned command name {node.id}')
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('mc_'):
            if node not in top_level or node.decorator_list:
                raise SourceError(f'{path}:{node.lineno}: unsupported conditional/nested/decorated command')
            result.append(
                Command(
                    command_name(node.name[3:]), 'python-function', node.name, Location('renode', path, node.lineno)
                )
            )
    return tuple(sorted(result, key=lambda item: item.name))

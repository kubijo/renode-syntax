"""Generate both parsers and validate pinned sources with their editor injection ranges."""

import ctypes
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import msgspec
import tyro
from corpus import Manifest
from csharp_source import ByteParser
from render_repl import ReplLexicon, scanner_header
from renode_model import SourceError
from rich.console import Console
from tree_sitter import Language, Node, Parser, Query, QueryCursor, Tree


def execute(root: Path, command: tuple[str, ...], cwd: Path | None = None) -> None:
    _ = subprocess.run(command, cwd=cwd or root, check=True)


GrammarName = Literal['resc', 'repl']
GRAMMARS: tuple[GrammarName, ...] = ('resc', 'repl')


def generate(root: Path, check: bool, name: GrammarName = 'resc') -> None:
    grammar = root / 'tree-sitter' / name
    output = root / '.tmp/tree-sitter/generated' / name if check else grammar / 'src'
    execute(root, ('tree-sitter', 'generate', '--output', str(output)), grammar)
    if name == 'repl':
        _ = shutil.copy2(grammar / 'scanner.c', output / 'scanner.c')
        data = msgspec.json.decode((root / 'generated/repl.json').read_bytes(), type=ReplLexicon)
        _ = (output / 'scanner-config.h').write_bytes(scanner_header(data))
    # The CLI omits final newlines on these JSON products; repository formatting requires them.
    for filename in ('grammar.json', 'node-types.json'):
        path = output / filename
        _ = path.write_bytes(path.read_bytes().rstrip(b'\n') + b'\n')
    if check:
        expected = {path.relative_to(output): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        actual = {
            path.relative_to(grammar / 'src'): path.read_bytes()
            for path in (grammar / 'src').rglob('*')
            if path.is_file()
        }
        if actual != expected:
            raise SourceError('Stale Tree-sitter src/; run just source::parser')


def build(root: Path, name: GrammarName = 'resc') -> Path:
    output = root / '.tmp/tree-sitter' / (name + '.so')
    output.parent.mkdir(parents=True, exist_ok=True)
    execute(root, ('tree-sitter', 'build', '--output', str(output), 'tree-sitter/' + name))
    return output


@dataclass(frozen=True)
class Grammar:
    library: ctypes.CDLL
    language: Language

    def parse(self, source: bytes) -> Tree:
        return cast(ByteParser, Parser(self.language)).parse(source)

    def parse_ranges(self, source: bytes, nodes: tuple[Node, ...]) -> Tree:
        parser = Parser(self.language)
        parser.included_ranges = [node.range for node in nodes]
        return cast(ByteParser, parser).parse(source)


def load(path: Path, name: GrammarName = 'resc') -> Grammar:
    library = ctypes.CDLL(str(path))
    function = getattr(library, 'tree_sitter_' + name)
    function.restype = ctypes.c_void_p
    pointer = function()
    capsule_new = ctypes.pythonapi.PyCapsule_New
    capsule_new.restype = ctypes.py_object
    capsule_new.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p)
    capsule = cast(object, capsule_new(pointer, b'tree_sitter.Language', None))
    return Grammar(library, Language(capsule))


def problems(node: Node) -> tuple[Node, ...]:
    # Include anonymous missing delimiters, which named_children would miss.
    if node.type == 'ERROR' or node.is_missing:
        return (node,)
    return tuple(problem for child in node.children for problem in problems(child))


def monitor_ranges(root: Path, grammar: Grammar, tree: Tree) -> tuple[tuple[Node, ...], ...]:
    """Use Zed's injection.host grouping, with one content range per query match."""
    query = Query(grammar.language, (root / 'integrations/zed/languages/repl/injections.scm').read_text())
    groups: dict[tuple[int, int], dict[tuple[int, int], Node]] = {}
    for pattern, captures in QueryCursor(query).matches(tree.root_node):
        if query.pattern_settings(pattern).get('injection.language') != 'Renode Script':
            continue
        hosts, content = captures.get('injection.host', []), captures.get('injection.content', [])
        if len(hosts) != 1 or len(content) != 1:
            raise SourceError('Each monitor injection must capture one fragment and its containing host')
        host, node = hosts[0], content[0]
        if node.parent != host:
            raise SourceError('A monitor injection fragment must belong to its captured host')
        group = groups.setdefault((host.start_byte, host.end_byte), {})
        group[node.start_byte, node.end_byte] = node
    return tuple(tuple(group[key] for key in sorted(group)) for group in groups.values())


def corpus(root: Path, grammar: Grammar, console: Console, name: GrammarName = 'resc') -> None:
    manifest = msgspec.json.decode((root / '.tmp/corpus/manifest.json').read_bytes(), type=Manifest)
    inputs = tuple(item for item in manifest.files if Path(item.path).suffix == '.' + name)
    if not inputs:
        raise SourceError(f'No pinned {name} files in the corpus')
    failures = 0
    evidence = root / '.tmp/tree-sitter/corpus' / name
    evidence.mkdir(parents=True, exist_ok=True)
    monitor = load(build(root)) if name == 'repl' else None
    embedded = 0
    for item in inputs:
        source = (root / item.file).read_bytes()
        if hashlib.sha256(source).hexdigest() != item.sha256:
            raise SourceError(f'Modified corpus input: {item.path}; run just test::corpus')
        tree = grammar.parse(source)
        errors = list(problems(tree.root_node))
        if monitor is not None:
            for nodes in monitor_ranges(root, grammar, tree):
                node = nodes[0]
                embedded += 1
                inner = monitor.parse_ranges(source, nodes)
                if problems(inner.root_node):
                    errors.append(node)
                    _ = (
                        evidence / (item.path.replace('/', '__') + '-monitor-' + str(node.start_byte) + '.txt')
                    ).write_text(str(inner.root_node) + '\n' + b''.join(part.text or b'' for part in nodes).decode())
        if errors:
            failures += 1
            output = evidence / (item.path.replace('/', '__') + '.txt')
            _ = output.write_text(str(tree.root_node) + '\n')
            for node in errors[:5]:
                console.print(
                    f'{item.path}:{node.start_point.row + 1}:{node.start_point.column + 1}: {node.type}: {str(node.text)[:100]}'
                )
    if failures:
        raise SourceError(
            f'{failures}/{len(inputs)} {name} files have ERROR/MISSING nodes ({evidence.relative_to(root)})'
        )
    console.print(
        f'[green]PASS[/green] {len(inputs)} pinned {name} files, {embedded} embedded monitor blocks: zero ERROR/MISSING nodes.'
    )


def queries(root: Path, grammar: Grammar, name: GrammarName = 'resc') -> None:
    for path in sorted((root / 'integrations/zed/languages' / name).glob('*.scm')):
        _ = Query(grammar.language, path.read_text())


class TestGrammar(msgspec.Struct, frozen=True):
    name: str = 'resc'
    path: str = '.'
    scope: str = 'source.renode.resc'


class Author(msgspec.Struct, frozen=True):
    name: str


class Metadata(msgspec.Struct, frozen=True):
    version: str
    license: str
    description: str
    authors: tuple[Author, ...]
    links: dict[str, str]


class TestManifest(msgspec.Struct, frozen=True):
    metadata: Metadata
    grammars: tuple[TestGrammar, ...] = (TestGrammar(),)


def fixtures(root: Path, update: bool = False, name: GrammarName = 'resc') -> None:
    # The CLI discovers test/corpus next to the parser. Stage it under .tmp so product
    # directories contain only editor inputs and the CLI never uses a user cache.
    directory = root / '.tmp/tree-sitter/tests' / name
    shutil.copytree(root / 'tree-sitter' / name / 'src', directory / 'src', dirs_exist_ok=True)
    shutil.copytree(root / 'infra/tree-sitter' / name / 'test', directory / 'test', dirs_exist_ok=True)
    manifest = msgspec.json.decode((root / 'tree-sitter.json').read_bytes(), type=TestManifest)
    manifest = msgspec.structs.replace(manifest, grammars=(TestGrammar(name=name, scope='source.renode.' + name),))
    _ = (directory / 'tree-sitter.json').write_bytes(msgspec.json.encode(manifest))
    arguments = ('--update',) if update else ()
    execute(root, ('tree-sitter', 'test', '--grammar-path', str(directory), *arguments), directory)
    if update:
        shutil.copytree(
            directory / 'test/corpus', root / 'infra/tree-sitter' / name / 'test/corpus', dirs_exist_ok=True
        )


@dataclass(frozen=True)
class Arguments:
    action: tyro.conf.Positional[Literal['generate', 'check', 'build', 'corpus', 'test', 'update-tests']]
    grammar: Literal['all', 'resc', 'repl'] = 'all'


def main() -> int:
    arguments = tyro.cli(Arguments)
    action = arguments.action
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        for name in GRAMMARS if arguments.grammar == 'all' else (arguments.grammar,):
            if action in ('generate', 'check'):
                generate(root, action == 'check', name)
            else:
                output = build(root, name)
                if action in ('test', 'update-tests'):
                    fixtures(root, action == 'update-tests', name)
                elif action == 'corpus':
                    grammar = load(output, name)
                    queries(root, grammar, name)
                    corpus(root, grammar, console, name)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

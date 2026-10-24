"""Generate parsers and run the pinned monitor corpus through the native grammar."""

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
from renode_model import SourceError
from rich.console import Console
from tree_sitter import Language, Node, Parser, Query, Tree


def execute(root: Path, command: tuple[str, ...], cwd: Path | None = None) -> None:
    _ = subprocess.run(command, cwd=cwd or root, check=True)


def generate(root: Path, check: bool) -> None:
    grammar = root / 'tree-sitter/resc'
    output = root / '.tmp/tree-sitter/generated' if check else grammar / 'src'
    execute(root, ('tree-sitter', 'generate', '--output', str(output)), grammar)
    # The CLI omits final newlines on these JSON products; repository formatting requires them.
    for name in ('grammar.json', 'node-types.json'):
        path = output / name
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


def build(root: Path) -> Path:
    output = root / '.tmp/tree-sitter/resc.so'
    output.parent.mkdir(parents=True, exist_ok=True)
    execute(root, ('tree-sitter', 'build', '--output', str(output), 'tree-sitter/resc'))
    return output


@dataclass(frozen=True)
class Grammar:
    library: ctypes.CDLL
    language: Language

    def parse(self, source: bytes) -> Tree:
        return cast(ByteParser, Parser(self.language)).parse(source)


def load(path: Path) -> Grammar:
    library = ctypes.CDLL(str(path))
    function = library.tree_sitter_resc
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


def corpus(root: Path, grammar: Grammar, console: Console) -> None:
    manifest = msgspec.json.decode((root / '.tmp/corpus/manifest.json').read_bytes(), type=Manifest)
    inputs = tuple(item for item in manifest.files if Path(item.path).suffix == '.resc')
    if not inputs:
        raise SourceError('No pinned monitor scripts in the corpus')
    failures = 0
    evidence = root / '.tmp/tree-sitter/corpus'
    evidence.mkdir(parents=True, exist_ok=True)
    for item in inputs:
        source = (root / item.file).read_bytes()
        if hashlib.sha256(source).hexdigest() != item.sha256:
            raise SourceError(f'Modified corpus input: {item.path}; run just test::corpus')
        tree = grammar.parse(source)
        errors = problems(tree.root_node)
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
            f'{failures}/{len(inputs)} monitor scripts have ERROR/MISSING nodes ({evidence.relative_to(root)})'
        )
    console.print(f'[green]PASS[/green] {len(inputs)} pinned monitor scripts: zero ERROR/MISSING nodes.')


def queries(root: Path, grammar: Grammar) -> None:
    for path in sorted((root / 'zed/languages/resc').glob('*.scm')):
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


def fixtures(root: Path, update: bool = False) -> None:
    # The CLI discovers test/corpus next to the parser. Stage it under .tmp so product
    # directories contain only editor inputs and the CLI never uses a user cache.
    directory = root / '.tmp/tree-sitter/tests'
    shutil.copytree(root / 'tree-sitter/resc/src', directory / 'src', dirs_exist_ok=True)
    shutil.copytree(root / 'infra/tree-sitter/resc/test', directory / 'test', dirs_exist_ok=True)
    manifest = msgspec.json.decode((root / 'tree-sitter.json').read_bytes(), type=TestManifest)
    manifest = msgspec.structs.replace(manifest, grammars=(TestGrammar(),))
    _ = (directory / 'tree-sitter.json').write_bytes(msgspec.json.encode(manifest))
    arguments = ('--update',) if update else ()
    execute(root, ('tree-sitter', 'test', '--grammar-path', str(directory), *arguments), directory)
    if update:
        shutil.copytree(directory / 'test/corpus', root / 'infra/tree-sitter/resc/test/corpus', dirs_exist_ok=True)


@dataclass(frozen=True)
class Arguments:
    action: tyro.conf.Positional[Literal['generate', 'check', 'build', 'corpus', 'test', 'update-tests']]


def main() -> int:
    action = tyro.cli(Arguments).action
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        if action in ('generate', 'check'):
            generate(root, action == 'check')
        else:
            output = build(root)
            if action in ('test', 'update-tests'):
                fixtures(root, action == 'update-tests')
            elif action == 'corpus':
                grammar = load(output)
                queries(root, grammar)
                corpus(root, grammar, console)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

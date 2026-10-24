"""Prepare a local Zed dev extension without changing the repository's Git history."""

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import msgspec
import tyro
from rich.console import Console
from treesitter import execute


class GrammarSource(msgspec.Struct, forbid_unknown_fields=True):
    repository: str
    rev: str
    path: str


class Extension(msgspec.Struct, forbid_unknown_fields=True):
    id: str
    name: str
    version: str
    schema_version: int
    authors: tuple[str, ...]
    description: str
    repository: str
    grammars: dict[str, GrammarSource]


def prepare(root: Path, compiler: Path, console: Console) -> Path:
    metadata = msgspec.toml.decode((root / 'zed/extension.toml').read_bytes(), type=Extension)
    revision = subprocess.run(
        ('git', 'rev-parse', 'HEAD'), cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    digest = hashlib.sha256()
    for directory in ('zed', 'tree-sitter/resc'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    destination = root / '.tmp/zed/builds' / (revision[:12] + '-' + digest.hexdigest()[:12]) / 'extension'
    shutil.copytree(root / 'zed', destination, dirs_exist_ok=True)
    checkout = destination / 'grammars/resc'
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        execute(root, ('git', 'clone', '--quiet', '--no-hardlinks', root.as_uri(), str(checkout)))
    execute(root, ('git', '-C', str(checkout), 'remote', 'set-url', 'origin', root.as_uri()))
    # Zed checks out this same revision even for file:// repositories. Seed the working
    # parser in its disposable clone so uncommitted edits can be reviewed before a commit.
    # Its non-forced checkout preserves these files. The parent index and history are untouched.
    shutil.copytree(root / 'tree-sitter/resc/src', checkout / 'tree-sitter/resc/src', dirs_exist_ok=True)
    execute(root, ('git', '-C', str(checkout), 'checkout', '--quiet', revision))
    if (checkout / 'tree-sitter/resc/src/parser.c').read_bytes() != (
        root / 'tree-sitter/resc/src/parser.c'
    ).read_bytes():
        raise ValueError('The dev grammar checkout did not preserve the working parser')
    metadata.grammars['resc'] = GrammarSource(root.as_uri(), revision, 'tree-sitter/resc')
    _ = (destination / 'extension.toml').write_bytes(msgspec.toml.encode(metadata))
    src = checkout / 'tree-sitter/resc/src'
    wasm = destination / 'grammars/resc.wasm'
    execute(
        root,
        (
            str(compiler),
            '-fPIC',
            '-shared',
            '-Os',
            '-Wl,--export=tree_sitter_resc',
            '-o',
            str(wasm),
            '-I',
            str(src),
            str(src / 'parser.c'),
        ),
    )
    if wasm.read_bytes()[:8] != b'\0asm\x01\0\0\0':
        raise ValueError('The WASI compiler did not produce a core WebAssembly module')
    link = root / '.tmp/zed/extension'
    if link.is_symlink():
        link.unlink()
    link.symlink_to(destination.relative_to(link.parent), target_is_directory=True)
    console.print(f'[green]PASS[/green] Prepared Zed dev extension: {link.relative_to(root)}')
    return destination


@dataclass(frozen=True)
class Arguments:
    compiler: Path


def main() -> int:
    arguments = tyro.cli(Arguments)
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        _ = prepare(root, arguments.compiler, console)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

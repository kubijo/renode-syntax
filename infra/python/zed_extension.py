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
from treesitter import GRAMMARS, execute


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
    for directory in ('zed', *(f'tree-sitter/{name}' for name in GRAMMARS)):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    destination = root / '.tmp/zed/builds' / (revision[:12] + '-' + digest.hexdigest()[:12]) / 'extension'
    shutil.copytree(root / 'zed', destination, dirs_exist_ok=True)
    for name in GRAMMARS:
        prepare_grammar(root, destination, metadata, revision, name, compiler)
    _ = (destination / 'extension.toml').write_bytes(msgspec.toml.encode(metadata))
    _ = shutil.copy2(root / 'infra/zed/review.repl', root / '.tmp/zed/review.repl')
    link = root / '.tmp/zed/extension'
    if link.is_symlink():
        link.unlink()
    link.symlink_to(destination.relative_to(link.parent), target_is_directory=True)
    console.print(f'[green]PASS[/green] Prepared Zed dev extension: {link.relative_to(root)}')
    return destination


def prepare_grammar(
    root: Path, destination: Path, metadata: Extension, revision: str, name: str, compiler: Path
) -> None:
    checkout = destination / 'grammars' / name
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        execute(root, ('git', 'clone', '--quiet', '--no-hardlinks', root.as_uri(), str(checkout)))
    execute(root, ('git', '-C', str(checkout), 'remote', 'set-url', 'origin', root.as_uri()))
    # Zed checks out this same revision even for file:// repositories. Seed the working
    # parser in its disposable clone so uncommitted edits can be reviewed before a commit.
    # Its non-forced checkout preserves these files. The parent index and history are untouched.
    relative = Path('tree-sitter') / name / 'src'
    shutil.copytree(root / relative, checkout / relative, dirs_exist_ok=True)
    execute(root, ('git', '-C', str(checkout), 'checkout', '--quiet', revision))
    if any(
        (checkout / relative / path.name).read_bytes() != path.read_bytes()
        for path in (root / relative).glob('*')
        if path.is_file()
    ):
        raise ValueError('The dev grammar checkout did not preserve the working parser')
    metadata.grammars[name] = GrammarSource(root.as_uri(), revision, 'tree-sitter/' + name)
    src = checkout / relative
    wasm = destination / 'grammars' / (name + '.wasm')
    execute(
        root,
        (
            str(compiler),
            '-fPIC',
            '-shared',
            '-Os',
            '-Wl,--export=tree_sitter_' + name,
            '-o',
            str(wasm),
            '-I',
            str(src),
            str(src / 'parser.c'),
            *((str(src / 'scanner.c'),) if (src / 'scanner.c').exists() else ()),
        ),
    )
    if wasm.read_bytes()[:8] != b'\0asm\x01\0\0\0':
        raise ValueError('The WASI compiler did not produce a core WebAssembly module')


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

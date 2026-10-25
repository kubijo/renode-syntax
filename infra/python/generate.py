"""Fetch pinned source inputs, derive facts, and render or verify committed products."""

import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import csharp_source
import msgspec
import render_repl
import render_treesitter
import tyro
import upstream
from extract_commands import csharp_commands, python_commands
from extract_platform import Platform
from extract_tokens import tokenizer
from render_sublime import grammars
from renode_model import RenodeData, SourceError
from rich.console import Console

UI = 'src/Emulator/Extensions/UserInterface'
GRAMMAR = 'src/Renode/PlatformDescription/Syntax/Grammar.cs'


def extract(root: Path) -> RenodeData:
    pins = upstream.read_pins(root)
    sources = upstream.validate(root, pins)
    renode = upstream.directory(root, 'renode')
    infrastructure = upstream.directory(root, 'infrastructure')
    platform = Platform(csharp_source.load('renode', renode, GRAMMAR))
    command_files = sorted((infrastructure / UI / 'Commands').rglob('*.cs'))
    documents = tuple(
        csharp_source.load('infrastructure', infrastructure, path.relative_to(infrastructure).as_posix())
        for path in command_files
    )
    commands = csharp_commands(documents, csharp_source.load('infrastructure', infrastructure, f'{UI}/Monitor.cs'))
    commands += python_commands((renode / 'scripts/monitor.py').read_text())
    if len({command.name for command in commands}) != len(commands):
        raise SourceError('Full command names must be unique across C# and the default Python script')
    return RenodeData(
        1,
        pins,
        sources,
        commands,
        platform.keywords(),
        tokenizer(csharp_source.load('infrastructure', infrastructure, f'{UI}/Tokenizer/Tokenizer.cs')),
        platform.lexical_rules(),
    )


def products(root: Path) -> dict[str, bytes]:
    data = extract(root)
    result = {'generated/renode.json': msgspec.json.format(msgspec.json.encode(data), indent=2) + b'\n'}
    result.update(grammars(root, data))
    result.update(render_treesitter.products(root, data))
    result.update(render_repl.products(root, data))
    return result


def synchronize(root: Path, expected: dict[str, bytes], check: bool, console: Console) -> int:
    stale: list[str] = []
    for name, content in expected.items():
        destination = root / name
        current = destination.read_bytes() if destination.exists() else b''
        if current == content:
            continue
        if check:
            stale.append(name)
            evidence = root / '.tmp/generation' / (Path(name).name + '.diff')
            evidence.parent.mkdir(parents=True, exist_ok=True)
            _ = evidence.write_text(
                ''.join(
                    difflib.unified_diff(
                        current.decode().splitlines(True),
                        content.decode().splitlines(True),
                        fromfile=name,
                        tofile=f'{name} (regenerated)',
                    )
                )
            )
            console.print(f'[red]STALE[/red] {name} ({evidence.relative_to(root)})')
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _ = destination.write_bytes(content)
            console.print(f'[green]WRITE[/green] {name}')
    if stale:
        console.print('Run just source::generate after reviewing the upstream changes.')
        return 1
    console.print('[green]PASS[/green] Generated data and Sublime grammars are current.')
    return 0


@dataclass(frozen=True)
class Arguments:
    action: tyro.conf.Positional[Literal['fetch', 'generate', 'check']]


def main() -> int:
    action = tyro.cli(Arguments).action
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        if action == 'fetch':
            upstream.fetch(root)
            console.print('[green]PASS[/green] Pinned upstream inputs are ready.')
            return 0
        return synchronize(root, products(root), action == 'check', console)
    except (OSError, ValueError, msgspec.DecodeError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

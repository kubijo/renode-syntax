"""Inspect tool provenance and render it without interpreting tool output as markup."""

import importlib.metadata
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import msgspec
from rich.console import Console
from rich.text import Text


class Locked(msgspec.Struct):
    rev: str | None = None


class Original(msgspec.Struct):
    ref: str | None = None


class Node(msgspec.Struct):
    locked: Locked | None = None
    original: Original | None = None


class FlakeLock(msgspec.Struct):
    nodes: dict[str, Node]


@dataclass(frozen=True)
class Pin:
    name: str
    revision: str
    version: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    origin: str
    arguments: tuple[str, ...] = ('--version',)
    executable: str | None = None


@dataclass(frozen=True)
class Report:
    name: str
    version: str
    location: Path | None
    origin: str
    problem: str | None = None


def read_pins(lockfile: Path) -> tuple[Pin, ...]:
    lock = msgspec.json.decode(lockfile.read_bytes(), type=FlakeLock)
    pins: list[Pin] = []
    for key in ('nixpkgs', 'nix-tools', 'nixpkgs-pinned'):
        node = lock.nodes.get(key)
        if node is None or node.locked is None or not node.locked.rev:
            raise ValueError(f'{lockfile}: missing locked revision for {key}')
        version = node.original.ref if node.original is not None else None
        if key == 'nix-tools' and not version:
            raise ValueError(f'{lockfile}: missing release tag for nix-tools')
        pins.append(Pin(key, node.locked.rev, version))
    return tuple(pins)


def inspect_tool(tool: Tool, version: str | None = None) -> Report:
    executable = shutil.which(tool.executable or tool.name)
    if executable is None:
        return Report(tool.name, 'missing', None, tool.origin, 'executable not found')
    location = Path(executable)
    if version is None:
        result = subprocess.run((executable, *tool.arguments), capture_output=True, text=True, check=False)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0 or not output:
            return Report(tool.name, 'unknown', location, tool.origin, 'version command failed')
        version = output.splitlines()[0]
    problem = None
    if tool.origin != 'host bootstrap' and not location.resolve().is_relative_to('/nix/store'):
        problem = 'expected a Nix-provided executable'
    return Report(tool.name, version, location, tool.origin, problem)


def inspect_package(name: str) -> Report:
    package = importlib.metadata.distribution(name)
    return Report(
        name,
        package.version,
        Path(str(package.locate_file(name.replace('-', '_')))),
        'uv.lock / uv2nix',
    )


def render(console: Console, pins: tuple[Pin, ...], reports: tuple[Report, ...]) -> None:
    console.print('Declared pins', style='bold cyan')
    for pin in pins:
        console.print(Text(f'  {pin.name}: {pin.version or ""} {pin.revision}'.rstrip()), soft_wrap=True)
    console.print()
    for report in reports:
        style = 'red' if report.problem else 'green'
        console.print(Text.assemble((report.name + ': ', f'bold {style}'), report.version), soft_wrap=True)
        location = str(report.location) if report.location else 'not found'
        console.print(Text(f'  path: {location}', style='dim'), soft_wrap=True)
        console.print(Text(f'  origin: {report.origin}', style='dim'), soft_wrap=True)
        if report.problem:
            console.print(Text(report.problem, style='bold red'))
        console.print()


def run(root: Path, console: Console) -> int:
    pins = read_pins(root / 'flake.lock')
    tools = (
        *(
            Tool(name, 'Nix shell')
            for name in (
                'rustc',
                'cargo',
                'rustfmt',
                'node',
                'bash',
                'git',
                'pkg-config',
                'direnv',
                'uv',
                'nix',
                'tree-sitter',
                'emacs',
            )
        ),
        Tool('python', 'uv2nix environment'),
        *(Tool(name, 'nix-tools tool packages') for name in ('just', 'ruff', 'basedpyright')),
        Tool('cargo-clippy', 'Nix shell'),
        Tool('cc', 'Nix shell'),
        Tool('ld', 'Nix shell', ('-v',)),
        Tool('wasi-clang', 'Nix WASI toolchain', executable=str(Path(os.environ['WASI_SDK_PATH']) / 'bin/clang')),
    )
    reports = tuple(inspect_tool(tool) for tool in tools)
    if shutil.which('zed') is not None:
        reports += (inspect_tool(Tool('zed', 'host bootstrap')),)
    release = next(pin.version for pin in pins if pin.name == 'nix-tools')
    reports += tuple(inspect_tool(Tool(name, 'nix-tools'), f'nix-tools {release}') for name in ('repofmt', 'repochk'))
    reports += tuple(
        inspect_package(name)
        for name in ('rich', 'tyro', 'msgspec', 'fissix', 'tree-sitter', 'tree-sitter-c-sharp', 'tomli-w')
    )
    render(console, pins, reports)
    return int(any(report.problem for report in reports))

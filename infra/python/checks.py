"""Run repository checks with complete saved output and visible Rich summaries."""

import subprocess
from pathlib import Path

import msgspec
from rich.console import Console
from rich.text import Text


class Step(msgspec.Struct):
    name: str
    argv: tuple[str, ...]
    forward_arguments: bool = False


class Plan(msgspec.Struct):
    steps: tuple[Step, ...]


def run(root: Path, console: Console, name: str, command: tuple[str, ...]) -> int:
    output = root / '.tmp' / 'checks' / f'{name}.log'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8') as stream:
        try:
            result = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT, check=False)
            status = result.returncode if result.returncode >= 0 else 128 - result.returncode
        except OSError as error:
            _ = stream.write(f'{error}\n')
            status = 1
    label, style = ('PASS', 'green') if status == 0 else ('FAIL', 'red')
    console.print(Text.assemble((label, f'bold {style}'), f' {name} ({output})'))
    return status


def execute_plan(root: Path, console: Console, planfile: Path, arguments: tuple[str, ...]) -> int:
    plan = msgspec.json.decode(planfile.read_bytes(), type=Plan)
    if arguments and not any(step.forward_arguments for step in plan.steps):
        raise ValueError('This command does not accept additional arguments')
    for step in plan.steps:
        command = step.argv + arguments if step.forward_arguments else step.argv
        status = run(root, console, step.name, command)
        if status:
            return status
    return 0

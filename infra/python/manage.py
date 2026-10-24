"""Run Nix-declared commands and structured diagnostics in the active shell."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import checks
import doctor
import tyro
from rich.console import Console
from rich.text import Text


@dataclass(frozen=True)
class Arguments:
    """Run a repository diagnostic or quality gate."""

    action: tyro.conf.Positional[Literal['doctor', 'run']]
    arguments: tyro.conf.Positional[tuple[str, ...]] = ()
    plan: Path | None = None
    color: Literal['auto', 'always', 'never'] = 'auto'


def execute(arguments: Arguments, root: Path, console: Console) -> int:
    if arguments.action == 'doctor':
        if arguments.arguments or arguments.plan is not None:
            raise ValueError('doctor does not accept a command plan or positional arguments')
        return doctor.run(root, console)
    if arguments.plan is None:
        raise ValueError('run requires the command plan supplied by Nix')
    return checks.execute_plan(root, console, arguments.plan, arguments.arguments)


def main() -> int:
    arguments = tyro.cli(Arguments)
    root = Path(__file__).resolve().parents[2]
    force_terminal = None if arguments.color == 'auto' else arguments.color == 'always'
    console = Console(record=True, force_terminal=force_terminal, highlight=False)
    try:
        if sys.version_info[:2] != (3, 15):
            raise ValueError('Repository tools require Python 3.15; enter the Nix development shell')
        return execute(arguments, root, console)
    except (OSError, ValueError) as error:
        console.print(Text(f'Error: {error}', style='bold red'))
        return 1
    finally:
        if arguments.action == 'doctor':
            output = root / '.tmp' / 'checks' / 'doctor.log'
            output.parent.mkdir(parents=True, exist_ok=True)
            console.save_text(str(output))


if __name__ == '__main__':
    sys.exit(main())

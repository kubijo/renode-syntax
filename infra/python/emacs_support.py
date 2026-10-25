"""Prepare native grammars and an isolated loader for Emacs review and tests."""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import msgspec
import tyro
from rich.console import Console
from treesitter import GRAMMARS, build


@dataclass(frozen=True)
class Arguments:
    python_grammar: Path
    suffix: str = '.so'


def prepare(root: Path, arguments: Arguments) -> None:
    directory = root / '.tmp/emacs/grammars'
    directory.mkdir(parents=True, exist_ok=True)
    for name in GRAMMARS:
        target = directory / ('libtree-sitter-' + name + arguments.suffix)
        pending = target.with_suffix(target.suffix + '.new')
        _ = shutil.copyfile(build(root, name), pending)
        _ = pending.replace(target)
    python = directory / ('libtree-sitter-python' + arguments.suffix)
    python.unlink(missing_ok=True)
    python.symlink_to(arguments.python_grammar.resolve(strict=True))
    _ = shutil.copyfile(root / 'infra/zed/review.repl', root / '.tmp/emacs/review.repl')

    def quoted(path: Path) -> str:
        return msgspec.json.encode(path.as_posix()).decode()

    _ = (root / '.tmp/emacs/setup.el').write_text(
        ';;; Generated local Emacs setup.\n'
        + f"(add-to-list 'load-path {quoted(root / 'integrations/emacs')})\n"
        + f"(add-to-list 'treesit-extra-load-path {quoted(directory)})\n"
        + f'(load-file {quoted(root / "integrations/emacs/renode-ts-data.el")})\n'
        + f'(load-file {quoted(root / "integrations/emacs/renode-ts-mode.el")})\n'
    )


def main() -> int:
    arguments = tyro.cli(Arguments)
    root = Path(__file__).resolve().parents[2]
    prepare(root, arguments)
    Console().print('[green]PASS[/green] Emacs setup: .tmp/emacs/setup.el')
    return 0


if __name__ == '__main__':
    sys.exit(main())

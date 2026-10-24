"""Fetch sparse, revision-checked generator inputs into the repository's disposable tree."""

import hashlib
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal

import msgspec
from renode_model import Pin, Pins, SourceError, SourceFile

Repository = Literal['renode', 'infrastructure']


def entries(pins: Pins) -> tuple[tuple[Repository, Pin], ...]:
    return (('renode', pins.renode), ('infrastructure', pins.infrastructure))


def read_pins(root: Path) -> Pins:
    pins = msgspec.json.decode((root / 'infra/renode-pins.json').read_bytes(), type=Pins)
    for pin in (pins.renode, pins.infrastructure):
        if len(pin.revision) != 40 or any(char not in '0123456789abcdef' for char in pin.revision):
            raise SourceError(f'Invalid upstream revision: {pin.revision!r}')
        if not pin.repository.startswith('https://github.com/renode/') or not pin.repository.endswith('.git'):
            raise SourceError(f'Unexpected upstream repository: {pin.repository!r}')
        if not pin.paths:
            raise SourceError('An upstream pin must specify its extraction inputs')
        for path in pin.paths:
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or '..' in parsed.parts or str(parsed) != path:
                raise SourceError(f'Invalid sparse input path: {path!r}')
    return pins


def git(directory: Path, *arguments: str, network: bool = False) -> str:
    command = ['git', '-C', str(directory)]
    environment = dict(os.environ)
    if not network:
        environment['GIT_NO_LAZY_FETCH'] = '1'
    result = subprocess.run([*command, *arguments], env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f'exit status {result.returncode}'
        raise SourceError(f'git {" ".join(arguments)} in {directory}: {detail}')
    return result.stdout.strip()


def directory(root: Path, name: Literal['renode', 'infrastructure']) -> Path:
    return root / '.tmp/upstream' / ('renode' if name == 'renode' else 'renode-infrastructure')


def fetch(root: Path) -> None:
    pins = read_pins(root)
    for name, pin in entries(pins):
        checkout = directory(root, name)
        checkout.mkdir(parents=True, exist_ok=True)
        if not (checkout / '.git').exists():
            _ = git(checkout, 'init', '--quiet')
            _ = git(checkout, 'remote', 'add', 'origin', pin.repository)
        if git(checkout, 'remote', 'get-url', 'origin') != pin.repository:
            raise SourceError(f'{checkout}: origin does not match the tracked pin')
        if git(checkout, 'status', '--porcelain', '--untracked-files=no'):
            raise SourceError(f'{checkout}: refusing to replace modified upstream inputs')
        _ = git(checkout, 'fetch', '--quiet', '--depth=1', '--filter=blob:none', 'origin', pin.revision, network=True)
        _ = git(checkout, 'sparse-checkout', 'set', '--no-cone', *(f'/{path}' for path in pin.paths), network=True)
        _ = git(checkout, 'checkout', '--quiet', '--detach', pin.revision, network=True)
    _ = validate(root, pins)


def validate(root: Path, pins: Pins) -> tuple[SourceFile, ...]:
    sources: list[SourceFile] = []
    for name, pin in entries(pins):
        checkout = directory(root, name)
        if not (checkout / '.git').is_dir():
            raise SourceError('Missing upstream checkout; run just source::fetch')
        if git(checkout, 'rev-parse', 'HEAD') != pin.revision:
            raise SourceError(f'{checkout}: HEAD does not match the tracked revision; run just source::fetch')
        _ = git(checkout, 'diff', '--exit-code', 'HEAD', '--', *pin.paths)
        if git(checkout, 'ls-files', '--others', '--', *pin.paths):
            raise SourceError(f'{checkout}: untracked files contaminate the pinned extraction inputs')
        for input_path in pin.paths:
            path = checkout / input_path
            if not path.exists():
                raise SourceError(f'Missing pinned input {path}; run just source::fetch')
            files = sorted(path.rglob('*.cs')) if path.is_dir() else [path]
            for file in files:
                sources.append(
                    SourceFile(
                        name, file.relative_to(checkout).as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()
                    )
                )
    gitlink = git(directory(root, 'renode'), 'ls-tree', 'HEAD', 'src/Infrastructure').split()
    if len(gitlink) != 4 or gitlink[0:2] != ['160000', 'commit'] or gitlink[2] != pins.infrastructure.revision:
        raise SourceError("The infrastructure pin does not match Renode's src/Infrastructure gitlink")
    return tuple(sources)

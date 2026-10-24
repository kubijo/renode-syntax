"""Materialize the complete pinned corpus from Git blobs for offline consumer gates."""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import msgspec
import tyro
import upstream
from renode_model import Pins, SourceError
from rich.console import Console


class Input(msgspec.Struct, frozen=True):
    repository: upstream.Repository
    revision: str
    path: str
    blob: str
    sha256: str
    file: str


class Manifest(msgspec.Struct, frozen=True):
    schema_version: Literal[1]
    pins: Pins
    files: tuple[Input, ...]


def blob_id(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content, usedforsecurity=False).hexdigest()


def parse_blobs(output: bytes, entries: tuple[upstream.CorpusFile, ...]) -> tuple[bytes, ...]:
    """Decode cat-file's size-framed protocol; blob contents may themselves contain NULs/newlines."""
    offset = 0
    result: list[bytes] = []
    for entry in entries:
        end = output.find(b'\n', offset)
        if end < 0:
            raise SourceError(f'Missing Git blob {entry.blob}; run just source::fetch')
        header = output[offset:end].decode('ascii').split()
        if len(header) != 3 or header[:2] != [entry.blob, 'blob'] or not header[2].isdigit():
            raise SourceError(f'Unavailable or malformed Git blob {entry.blob}; run just source::fetch')
        size = int(header[2])
        start = end + 1
        offset = start + size + 1
        content = output[start : start + size]
        if output[start + size : offset] != b'\n' or blob_id(content) != entry.blob:
            raise SourceError(f'Truncated or corrupt pinned blob: {entry.path}')
        result.append(content)
    if offset != len(output):
        raise SourceError('Unexpected trailing data in the Git blob stream')
    return tuple(result)


def read_blobs(checkout: Path, entries: tuple[upstream.CorpusFile, ...]) -> tuple[bytes, ...]:
    if not entries:
        return ()
    result = subprocess.run(
        ['git', '-C', str(checkout), 'cat-file', '--batch'],
        input=''.join(entry.blob + '\n' for entry in entries).encode(),
        capture_output=True,
        env=upstream.git_environment(),
        check=False,
    )
    if result.returncode:
        raise SourceError(
            f'Cannot read the pinned corpus offline; run just source::fetch: {result.stderr.decode().strip()}'
        )
    return parse_blobs(result.stdout, entries)


def prepare(root: Path, console: Console) -> Manifest:
    pins = upstream.read_pins(root)
    _ = upstream.validate(root, pins)
    files: list[Input] = []
    for repository, pin in upstream.entries(pins):
        checkout = upstream.directory(root, repository)
        entries = upstream.corpus_files(checkout, pin.revision)
        contents = read_blobs(checkout, entries)
        for entry, content in zip(entries, contents, strict=True):
            _ = content.decode('utf-8')
            relative = Path('.tmp/corpus/input') / repository / pin.revision / entry.path
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Recreate any edited materialization from the pinned blob, never from a working checkout.
            if not destination.exists() or destination.read_bytes() != content:
                _ = destination.write_bytes(content)
            files.append(
                Input(
                    repository,
                    pin.revision,
                    entry.path,
                    entry.blob,
                    hashlib.sha256(content).hexdigest(),
                    relative.as_posix(),
                )
            )
    for suffix in ('.repl', '.resc'):
        if not any(Path(item.path).suffix == suffix for item in files):
            raise SourceError(f'The pinned corpus has no {suffix} inputs')
    manifest = Manifest(1, pins, tuple(files))
    output = root / '.tmp/corpus'
    output.mkdir(parents=True, exist_ok=True)
    _ = (output / 'manifest.json').write_bytes(msgspec.json.format(msgspec.json.encode(manifest), indent=2) + b'\n')
    # A NUL-delimited view lets the Rust runner consume paths without another serialization dependency.
    _ = (output / 'files0').write_bytes(b''.join(item.file.encode() + b'\0' for item in files))
    console.print(
        f'[green]PASS[/green] Prepared {len(files)} pinned corpus files ({output.relative_to(root) / "manifest.json"}).'
    )
    return manifest


@dataclass(frozen=True)
class Arguments:
    """Prepare the pinned corpus for consumer gates without network access."""

    action: tyro.conf.Positional[Literal['prepare']]


def main() -> int:
    _ = tyro.cli(Arguments)
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        _ = prepare(root, console)
        return 0
    except (OSError, ValueError, msgspec.DecodeError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

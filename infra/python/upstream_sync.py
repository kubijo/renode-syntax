"""Prepare isolated upstream updates; publish only in the explicit publication modes."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import msgspec
import sync_github
import sync_model
import tyro
import upstream
from renode_model import Pins, SourceError
from rich.console import Console


class DispatchInputs(msgspec.Struct, frozen=True):
    dry_run: bool | Literal['true', 'false'] = True


class Event(msgspec.Struct):
    inputs: DispatchInputs = DispatchInputs()


@dataclass(frozen=True)
class Arguments:
    action: tyro.conf.Positional[Literal['dry-run', 'replay', 'publish', 'ci']]
    gate: Path
    python_environment: Path
    base_renode: str | None = None
    target_renode: str | None = None


def revision(value: str) -> str:
    if re.fullmatch('[0-9a-f]{40}', value) is None:
        raise SourceError(f'Expected a full lowercase Git revision, got {value!r}')
    return value


def ci_publication(event_name: str, event: bytes) -> bool:
    if event_name == 'schedule':
        return True
    if event_name != 'workflow_dispatch':
        raise SourceError(f'Unsupported sync event: {event_name!r}')
    inputs = msgspec.json.decode(event, type=Event).inputs
    return inputs.dry_run is False or inputs.dry_run == 'false'


def workspace(root: Path) -> Path:
    runs = root / '.tmp/sync/runs'
    runs.mkdir(parents=True, exist_ok=True)
    checkout = Path(tempfile.mkdtemp(prefix='update-', dir=runs)) / 'worktree'
    _ = upstream.git(root, 'worktree', 'add', '--quiet', '--detach', str(checkout), 'HEAD')
    # Include local tooling edits in dry runs without staging them or changing the caller's branch.
    names = upstream.git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0')
    for name in filter(None, names):
        source, destination = root / name, checkout / name
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
        if not source.exists() and not source.is_symlink():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            destination.symlink_to(source.readlink())
        else:
            _ = shutil.copy2(source, destination)
    return checkout


def initialize_inputs(checkout: Path, pins: Pins) -> None:
    for name, pin in upstream.entries(pins):
        destination = upstream.directory(checkout, name)
        destination.mkdir(parents=True)
        _ = upstream.git(destination, 'init', '--quiet')
        _ = upstream.git(destination, 'remote', 'add', 'origin', pin.repository)


def resolve(checkout: Path, pins: Pins, value: str | None) -> Pins:
    repository = upstream.directory(checkout, 'renode')
    if value is None:
        advertised = upstream.git(repository, 'ls-remote', 'origin', 'HEAD', network=True).split()
        if len(advertised) != 2 or advertised[1] != 'HEAD':
            raise SourceError('Renode origin did not advertise exactly one HEAD')
        value = advertised[0]
    value = revision(value)
    _ = upstream.git(repository, 'fetch', '--quiet', '--depth=1', '--filter=blob:none', 'origin', value, network=True)
    link = upstream.git(repository, 'ls-tree', value, 'src/Infrastructure').split()
    if len(link) != 4 or link[:2] != ['160000', 'commit'] or link[3] != 'src/Infrastructure':
        raise SourceError('Renode is missing its src/Infrastructure gitlink')
    return Pins(
        msgspec.structs.replace(pins.renode, revision=value),
        msgspec.structs.replace(pins.infrastructure, revision=revision(link[2])),
    )


def structural_changes(checkout: Path, base: Pins, target: Pins) -> tuple[sync_model.StructuralChange, ...]:
    repository = upstream.directory(checkout, 'renode')
    changes: list[sync_model.StructuralChange] = []
    for path in sync_model.STRUCTURAL:
        blobs: list[str | None] = []
        for pin in (base, target):
            entry = upstream.git(repository, 'ls-tree', pin.renode.revision, path).split()
            if not entry:
                blobs.append(None)
            elif len(entry) == 4 and entry[:2] == ['100644', 'blob'] and entry[3] == path:
                blobs.append(revision(entry[2]))
            else:
                raise SourceError(f'Unsupported structural source tree entry: {path}')
        if blobs[0] != blobs[1] or blobs[0] is None:
            changes.append(sync_model.StructuralChange(path, blobs[0], blobs[1]))
    return tuple(changes)


def execute(checkout: Path, environment: dict[str, str], name: str, argv: tuple[str, ...]) -> None:
    output = checkout / '.tmp/checks' / f'sync-{name}.log'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w') as stream:
        result = subprocess.run(
            argv, cwd=checkout, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False
        )
    if result.returncode:
        raise SourceError(f'{name} exited {result.returncode}; see {output}')


def regenerate(checkout: Path, pins: Pins, environment: dict[str, str]) -> None:
    _ = (checkout / 'infra/renode-pins.json').write_bytes(
        msgspec.json.format(msgspec.json.encode(pins), indent=2) + b'\n'
    )
    for name, script, action in (
        ('fetch', 'generate.py', 'fetch'),
        ('generate', 'generate.py', 'generate'),
        ('parser', 'treesitter.py', 'generate'),
    ):
        execute(checkout, environment, name, (sys.executable, 'infra/python/' + script, action))


def save(root: Path, checkout: Path, report: sync_model.Report, difference: str) -> Path:
    artifacts = root / '.tmp/sync/artifacts'
    if artifacts.exists():
        shutil.rmtree(artifacts)
    artifacts.mkdir(parents=True)
    _ = (artifacts / 'report.json').write_bytes(msgspec.json.format(msgspec.json.encode(report), indent=2) + b'\n')
    _ = (artifacts / 'update.patch').write_text(difference)
    for name, content in (('pull-request', report.pull_request), ('issue', report.issue)):
        _ = (artifacts / f'{name}.md').write_text('' if content is None else content.title + '\n\n' + content.body)
    _ = (artifacts / 'workspace.txt').write_text(str(checkout) + '\n')
    for directory in ('.tmp/checks', '.tmp/generation', '.tmp/tree-sitter/corpus'):
        source = checkout / directory
        if source.is_dir():
            _ = shutil.copytree(source, artifacts / directory.removeprefix('.tmp/'))
    return artifacts


def prepare(root: Path, arguments: Arguments, console: Console) -> tuple[sync_model.Report, Path]:
    original = upstream.read_pins(root)
    checkout = workspace(root)
    base, target = original, None
    stage = 'resolving upstream pins'
    difference = ''
    expected: tuple[str, ...] | None = None
    try:
        initialize_inputs(checkout, original)
        old_revision, new_revision = arguments.base_renode, arguments.target_renode
        if arguments.action == 'replay':
            if old_revision is not None or new_revision is not None:
                raise SourceError('Replay uses the checked fixture; use dry-run for custom revisions')
            fixture = msgspec.json.decode((root / 'infra/ci/sync-replay.json').read_bytes(), type=sync_model.Replay)
            old_revision, new_revision, expected = fixture.base_renode, fixture.target_renode, fixture.expected_files
        base = resolve(checkout, original, old_revision or original.renode.revision)
        if old_revision is None and base != original:
            raise SourceError('The tracked infrastructure pin does not match the starting Renode gitlink')
        target = resolve(checkout, original, new_revision)
        changes = structural_changes(checkout, base, target)
        if changes:
            report = sync_model.structural_report(base, target, changes)
        else:
            environment = dict(os.environ)
            environment['RENODE_SYNTAX_ROOT'] = str(checkout)
            environment['CARGO_TARGET_DIR'] = str(checkout / '.tmp/cargo-target/syntax-test')
            (checkout / '.tmp/venv').mkdir(parents=True)
            (checkout / '.tmp/venv/nix').symlink_to(arguments.python_environment)
            if old_revision is not None:
                stage = 'regenerating the replay baseline'
                regenerate(checkout, base, environment)
            before = sync_model.products(checkout)
            stage = 'regenerating the candidate'
            regenerate(checkout, target, environment)
            stage = 'running the complete quality gate'
            execute(checkout, environment, 'gate', (str(arguments.gate),))
            report, difference = sync_model.proposal(base, target, before, sync_model.products(checkout))
            if expected is not None and report.files != expected:
                raise SourceError(f'Replay changed {report.files!r}, expected {expected!r}')
    except (OSError, ValueError, msgspec.DecodeError) as error:
        report = sync_model.failure_report(base, target, stage, str(error))
        difference = ''
    artifacts = save(root, checkout, report, difference)
    console.print(f'[bold]{report.status}[/bold]: {artifacts}')
    return report, checkout


def publication_context(root: Path, api: sync_github.GitHub) -> None:
    if upstream.git(root, 'status', '--porcelain'):
        raise SourceError('Publication requires a clean working tree')
    origin = upstream.git(root, 'remote', 'get-url', 'origin')
    normalized = origin.replace('git@github.com:', 'https://github.com/').removesuffix('.git')
    if normalized != 'https://github.com/' + api.repository:
        raise SourceError('The publication repository does not match origin')
    branch = upstream.git(root, 'symbolic-ref', '--short', 'HEAD')
    if branch != api.default_branch():
        raise SourceError('Publication must start from the repository default branch')


def main() -> int:
    arguments = tyro.cli(Arguments)
    root = Path(__file__).resolve().parents[2]
    console = Console(highlight=False)
    try:
        publish = arguments.action == 'publish'
        if arguments.action == 'ci':
            publish = ci_publication(
                os.environ['GITHUB_EVENT_NAME'], Path(os.environ['GITHUB_EVENT_PATH']).read_bytes()
            )
        api: sync_github.GitHub | None = None
        if publish:
            if arguments.base_renode is not None or arguments.target_renode is not None:
                raise SourceError('Custom pins are supported only by dry-run')
            api = sync_github.GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN'])
            publication_context(root, api)
        report, checkout = prepare(root, arguments, console)
        if api is not None:
            url = sync_github.publish(root, checkout, report, api)
            if url:
                console.print(url)
        return 0 if report.status in ('updated', 'unchanged') else 1
    except (OSError, ValueError, KeyError, msgspec.DecodeError) as error:
        console.print(f'[red]FAIL[/red] {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

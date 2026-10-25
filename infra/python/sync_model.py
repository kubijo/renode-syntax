"""Typed sync proposals and review decisions, independent of GitHub publication."""

import difflib
from pathlib import Path
from typing import Literal

import msgspec
from renode_model import Pins, RenodeData
from treesitter import GRAMMARS

BRANCH = 'automation/renode-sync'
STRUCTURAL = (
    'src/Renode/PlatformDescription/Syntax/Grammar.cs',
    'src/Renode/PlatformDescription/PreLexer.cs',
)


class Content(msgspec.Struct, frozen=True):
    title: str
    body: str


class StructuralChange(msgspec.Struct, frozen=True):
    path: str
    before: str | None
    after: str | None


class Report(msgspec.Struct, frozen=True):
    schema_version: Literal[1]
    status: Literal['unchanged', 'updated', 'needs-review', 'failed']
    base: Pins
    target: Pins | None
    files: tuple[str, ...] = ()
    structural: tuple[StructuralChange, ...] = ()
    pull_request: Content | None = None
    issue: Content | None = None
    failure: str | None = None


class Replay(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    base_renode: str
    target_renode: str
    expected_files: tuple[str, ...]


def products(root: Path) -> dict[str, bytes]:
    paths = [root / 'infra/renode-pins.json']
    for directory in ('generated', *(f'tree-sitter/{name}/src' for name in GRAMMARS)):
        paths.extend(path for path in (root / directory).rglob('*') if path.is_file())
    paths.extend((root / 'integrations/sublime').glob('*.sublime-syntax'))
    paths.extend((root / 'integrations/zed/languages').rglob('highlights.scm'))
    paths.extend((root / 'integrations/zed/languages').rglob('brackets.scm'))
    paths.extend((root / 'integrations/emacs').glob('renode-ts-data.el'))
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(paths)}


def patch(before: dict[str, bytes], after: dict[str, bytes]) -> tuple[tuple[str, ...], str]:
    changed = tuple(name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name))
    chunks: list[str] = []
    for name in changed:
        chunks.append(f'diff --git a/{name} b/{name}\n')
        chunks.extend(
            difflib.unified_diff(
                before.get(name, b'').decode().splitlines(True),
                after.get(name, b'').decode().splitlines(True),
                fromfile=f'a/{name}' if name in before else '/dev/null',
                tofile=f'b/{name}' if name in after else '/dev/null',
            )
        )
    return changed, ''.join(chunks)


def pin_summary(base: Pins, target: Pins) -> str:
    return (
        f'- Renode: `{base.renode.revision}` -> `{target.renode.revision}`\n'
        f'- Infrastructure: `{base.infrastructure.revision}` -> `{target.infrastructure.revision}`\n'
        "- Infrastructure follows Renode's recorded `src/Infrastructure` gitlink.\n"
    )


def fact_summary(before: bytes, after: bytes) -> str:
    old = msgspec.json.decode(before, type=RenodeData)
    new = msgspec.json.decode(after, type=RenodeData)
    lines: list[str] = []
    for label, old_names, new_names in (
        ('Commands', {item.name for item in old.commands}, {item.name for item in new.commands}),
        ('Keywords', {item.name for item in old.keywords}, {item.name for item in new.keywords}),
    ):
        for operation, names in (('added', new_names - old_names), ('removed', old_names - new_names)):
            if names:
                lines.append(f'- {label} {operation}: ' + ', '.join(f'`{name}`' for name in sorted(names)))
    old_tokens = tuple((rule.order, rule.kind, rule.dotnet, rule.options) for rule in old.tokenizer)
    new_tokens = tuple((rule.order, rule.kind, rule.dotnet, rule.options) for rule in new.tokenizer)
    if old_tokens != new_tokens:
        lines.append('- Tokenizer rules changed; regenerated all consumers.')
    return (
        '\n'.join(lines)
        or '- Commands, keywords and tokenizer rules are unchanged; refreshed pins and source provenance.'
    )


def proposal(base: Pins, target: Pins, before: dict[str, bytes], after: dict[str, bytes]) -> tuple[Report, str]:
    files, difference = patch(before, after)
    if not files:
        return Report(1, 'unchanged', base, target), difference
    body = (
        '<!-- renode-syntax:upstream-sync -->\n'
        'Update the pinned Renode inputs and regenerate the editor products.\n\n'
        + pin_summary(base, target)
        + '\n'
        + fact_summary(before['generated/renode.json'], after['generated/renode.json'])
        + '\n\nChanged files:\n\n'
        + '\n'.join(f'- `{name}`' for name in files)
        + '\n\nValidation: the complete Nix-defined quality gate passed, including both pinned-corpus checks.\n'
    )
    return Report(
        1, 'updated', base, target, files, pull_request=Content('Update pinned Renode syntax sources', body)
    ), difference


def structural_report(base: Pins, target: Pins, changes: tuple[StructuralChange, ...]) -> Report:
    body = (
        '<!-- renode-syntax:structural-review -->\n'
        'Renode changed a structural platform-language source. Review the grammar and prelexer before advancing pins.\n\n'
        + pin_summary(base, target)
        + '\n'
        + '\n'.join(f'- `{item.path}`: `{item.before}` -> `{item.after}`' for item in changes)
        + f'\n\n[Upstream comparison](https://github.com/renode/renode/compare/{base.renode.revision}...{target.renode.revision})\n'
        + '\nNo update branch or pull request was published.\n'
    )
    return Report(
        1,
        'needs-review',
        base,
        target,
        structural=changes,
        issue=Content('Review upstream Renode structural changes', body),
    )


def failure_report(base: Pins, target: Pins | None, stage: str, error: str) -> Report:
    detail = error[:4000].replace('```', r'\`\`\`')
    body = (
        '<!-- renode-syntax:gate-failure -->\n'
        f'The upstream sync failed during {stage}. Inspect the saved workflow artifacts before advancing pins.\n\n'
        + (pin_summary(base, target) if target is not None else f'- Starting Renode pin: `{base.renode.revision}`\n')
        + f'\nFailure:\n\n```text\n{detail}\n```\n\nNo update branch or pull request was published.\n'
    )
    return Report(
        1, 'failed', base, target, issue=Content('Investigate upstream Renode sync failure', body), failure=error
    )

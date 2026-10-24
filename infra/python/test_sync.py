"""Guard sync review gates, dry-run isolation and ownership of GitHub publications."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import msgspec
import sync_github
import sync_model
import upstream
import upstream_sync
from renode_model import Pins, RenodeData, SourceError
from rich.console import Console

ROOT = Path(__file__).resolve().parents[2]
PINS = upstream.read_pins(ROOT)
TARGET = Pins(msgspec.structs.replace(PINS.renode, revision='a' * 40), PINS.infrastructure)
DATA = msgspec.json.decode((ROOT / 'generated/renode.json').read_bytes(), type=RenodeData)
CONTENT = sync_model.Content('Update', sync_github.MARKER + '\nChecked update.')


class FakeGitHub(sync_github.GitHub):
    def __init__(self, responses: tuple[bytes, ...]) -> None:
        super().__init__('kubijo/renode-syntax', 'test-token')
        self.responses: list[bytes] = list(responses)
        self.calls: list[tuple[str, msgspec.Struct | None, str]] = []

    def call(self, endpoint: str, payload: msgspec.Struct | None = None, method: str = 'GET') -> bytes:
        self.calls.append((endpoint, payload, method))
        if not self.responses:
            raise AssertionError(f'Unexpected GitHub request: {method} {endpoint}')
        return self.responses.pop(0)


def issue(body: str, *, pull: bool = False) -> sync_github.Issue:
    return sync_github.Issue(
        7,
        'Update',
        body,
        'https://github.com/kubijo/renode-syntax/issues/7',
        sync_github.PullReference('pull') if pull else None,
    )


def write_products(root: Path, pins: Pins) -> None:
    (root / 'infra').mkdir(exist_ok=True)
    (root / 'generated').mkdir(exist_ok=True)
    _ = (root / 'infra/renode-pins.json').write_bytes(msgspec.json.encode(pins))
    _ = (root / 'generated/renode.json').write_bytes(msgspec.json.encode(msgspec.structs.replace(DATA, pins=pins)))


class ProposalTests(unittest.TestCase):
    def test_patch_covers_changed_added_and_deleted_products(self) -> None:
        names, difference = sync_model.patch({'old': b'old\n', 'same': b'x\n'}, {'new': b'new\n', 'same': b'x\n'})
        self.assertEqual(names, ('new', 'old'))
        self.assertIn('--- /dev/null\n+++ b/new', difference)
        self.assertIn('--- a/old\n+++ /dev/null', difference)

    def test_unchanged_products_do_not_propose_a_pr(self) -> None:
        report, difference = sync_model.proposal(PINS, PINS, {}, {})
        self.assertEqual(report.status, 'unchanged')
        self.assertIsNone(report.pull_request)
        self.assertEqual(difference, '')

    def test_default_dispatch_is_read_only_and_bad_input_is_rejected(self) -> None:
        for payload in (b'{}', b'{"inputs":{"dry_run":true}}', b'{"inputs":{"dry_run":"true"}}'):
            self.assertFalse(upstream_sync.ci_publication('workflow_dispatch', payload))
        for payload in (b'{"inputs":{"dry_run":false}}', b'{"inputs":{"dry_run":"false"}}'):
            self.assertTrue(upstream_sync.ci_publication('workflow_dispatch', payload))
        self.assertTrue(upstream_sync.ci_publication('schedule', b'{}'))
        with self.assertRaises(msgspec.ValidationError):
            _ = upstream_sync.ci_publication('workflow_dispatch', b'{"inputs":{"dry_run":7}}')
        with self.assertRaises(SourceError):
            _ = upstream_sync.ci_publication('pull_request', b'{}')

    def test_gitlink_is_followed_instead_of_infrastructure_head(self) -> None:
        with patch('upstream.git', side_effect=['', '160000 commit ' + 'b' * 40 + '\tsrc/Infrastructure']) as git:
            resolved = upstream_sync.resolve(ROOT, PINS, 'a' * 40)
        self.assertEqual(resolved.infrastructure.revision, 'b' * 40)
        self.assertEqual(git.call_count, 2)
        with (
            patch('upstream.git', side_effect=['', '100644 blob ' + 'b' * 40 + '\tsrc/Infrastructure']),
            self.assertRaisesRegex(SourceError, 'gitlink'),
        ):
            _ = upstream_sync.resolve(ROOT, PINS, 'a' * 40)

    def test_changed_or_missing_structural_sources_require_review(self) -> None:
        path, prelexer = sync_model.STRUCTURAL
        unchanged = '100644 blob ' + 'c' * 40 + '\t' + prelexer
        for old, new in (('b' * 40, 'a' * 40), ('b' * 40, None), (None, None)):
            entries = [f'100644 blob {value}\t{path}' if value else '' for value in (old, new)]
            with patch('upstream.git', side_effect=[*entries, unchanged, unchanged]):
                self.assertEqual(
                    upstream_sync.structural_changes(ROOT, PINS, TARGET),
                    (sync_model.StructuralChange(path, old, new),),
                )

    def test_structural_review_blocks_generation_and_saves_issue(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sync-test-') as directory:
            root = Path(directory)
            checkout = root / 'worktree'
            checkout.mkdir()
            change = sync_model.StructuralChange(sync_model.STRUCTURAL[0], 'b' * 40, 'a' * 40)
            with (
                patch('upstream.read_pins', return_value=PINS),
                patch('upstream_sync.workspace', return_value=checkout),
                patch('upstream_sync.initialize_inputs'),
                patch('upstream_sync.resolve', side_effect=[PINS, TARGET]),
                patch('upstream_sync.structural_changes', return_value=(change,)),
                patch('upstream_sync.regenerate') as regenerate,
                patch('upstream_sync.execute') as gate,
            ):
                report, _ = upstream_sync.prepare(
                    root, upstream_sync.Arguments('dry-run', Path('gate'), Path('python')), Console(file=io.StringIO())
                )
            regenerate.assert_not_called()
            gate.assert_not_called()
            self.assertEqual(report.status, 'needs-review')
            self.assertIsNone(report.pull_request)
            self.assertIn('structural-review', (root / '.tmp/sync/artifacts/issue.md').read_text())
            self.assertEqual((root / '.tmp/sync/artifacts/update.patch').read_text(), '')

    def run_candidate(self, *, fail_gate: bool) -> sync_model.Report:
        with tempfile.TemporaryDirectory(prefix='sync-test-') as directory:
            root = Path(directory)
            checkout = root / 'worktree'
            checkout.mkdir()
            write_products(root, PINS)
            write_products(checkout, PINS)
            original = sync_model.products(root)

            def regenerate(worktree: Path, pins: Pins, _environment: dict[str, str]) -> None:
                write_products(worktree, pins)

            with (
                patch('upstream_sync.workspace', return_value=checkout),
                patch('upstream_sync.initialize_inputs'),
                patch('upstream_sync.resolve', side_effect=[PINS, TARGET]),
                patch('upstream_sync.structural_changes', return_value=()),
                patch('upstream_sync.regenerate', side_effect=regenerate),
                patch('upstream_sync.execute', side_effect=SourceError('fixture gate failure') if fail_gate else None),
                patch('sync_github.publish') as publish,
            ):
                report, _ = upstream_sync.prepare(
                    root, upstream_sync.Arguments('dry-run', Path('gate'), Path('python')), Console(file=io.StringIO())
                )
            publish.assert_not_called()
            self.assertEqual(sync_model.products(root), original)
            saved = msgspec.json.decode(
                (root / '.tmp/sync/artifacts/report.json').read_bytes(), type=sync_model.Report
            )
            self.assertEqual(saved, report)
            return report

    def test_gate_failure_produces_an_issue_and_no_pr(self) -> None:
        report = self.run_candidate(fail_gate=True)
        self.assertEqual(report.status, 'failed')
        self.assertIsNone(report.pull_request)
        self.assertIsNotNone(report.issue)

    def test_checked_update_contains_pins_provenance_and_validation(self) -> None:
        report = self.run_candidate(fail_gate=False)
        self.assertEqual(report.status, 'updated')
        self.assertEqual(report.files, ('generated/renode.json', 'infra/renode-pins.json'))
        assert report.pull_request is not None
        self.assertIn(TARGET.renode.revision, report.pull_request.body)
        self.assertIn('gitlink', report.pull_request.body)
        self.assertIn('complete Nix-defined quality gate passed', report.pull_request.body)


class PublicationTests(unittest.TestCase):
    def test_issue_is_updated_instead_of_duplicated_and_prs_are_excluded(self) -> None:
        marker = '<!-- renode-syntax:structural-review -->'
        content = sync_model.Content('Review', marker + '\nNew candidate')
        api = FakeGitHub((
            msgspec.json.encode((issue(marker), issue(marker, pull=True))),
            msgspec.json.encode(issue(content.body)),
        ))
        self.assertIn('/issues/7', api.issue(content))
        self.assertEqual([call[2] for call in api.calls], ['GET', 'PATCH'])

    def test_unchanged_issue_has_no_mutating_request(self) -> None:
        content = sync_model.Content('Update', '<!-- renode-syntax:gate-failure -->')
        api = FakeGitHub((msgspec.json.encode((issue(content.body),)),))
        _ = api.issue(content)
        self.assertEqual(len(api.calls), 1)

    def test_ambiguous_issues_unowned_pr_and_malformed_response_are_rejected(self) -> None:
        marker = '<!-- renode-syntax:gate-failure -->'
        api = FakeGitHub((msgspec.json.encode((issue(marker), issue(marker))),))
        with self.assertRaisesRegex(SourceError, 'Multiple'):
            _ = api.issue(sync_model.Content('Failure', marker))
        api = FakeGitHub((msgspec.json.encode((issue('unowned'),)),))
        with self.assertRaisesRegex(SourceError, 'unowned'):
            _ = api.pulls('main')
        api = FakeGitHub((b'{"default_branch":7}',))
        with self.assertRaises(msgspec.ValidationError):
            _ = api.default_branch()

    def test_publication_requires_clean_default_branch_and_matching_origin(self) -> None:
        for outputs, problem in (
            ([' M dirty'], 'clean'),
            (['', 'https://github.com/other/repo'], 'origin'),
            (['', 'https://github.com/kubijo/renode-syntax.git', 'feature'], 'default branch'),
        ):
            api = FakeGitHub((b'{"default_branch":"main"}',))
            with patch('upstream.git', side_effect=outputs), self.assertRaisesRegex(SourceError, problem):
                upstream_sync.publication_context(ROOT, api)

    def test_existing_owned_branch_is_updated_without_force_push(self) -> None:
        calls: list[tuple[str, ...]] = []
        old = 'b' * 40

        def git(_directory: Path, *argv: str, network: bool = False) -> str:
            _ = network
            calls.append(argv)
            if argv == ('remote', 'get-url', 'origin'):
                return 'https://github.com/kubijo/renode-syntax.git'
            if argv[0] == 'ls-remote':
                return old + '\trefs/heads/' + sync_model.BRANCH
            if argv == ('rev-parse', 'FETCH_HEAD'):
                return old
            if argv[0] == 'log':
                return sync_github.MARKER
            if argv[0] == 'write-tree':
                return 'new-tree'
            if argv == ('rev-parse', old + '^{tree}'):
                return 'old-tree'
            if argv == ('rev-parse', 'HEAD'):
                return 'a' * 40
            if 'commit-tree' in argv:
                return 'c' * 40
            return ''

        api = FakeGitHub((b'{"default_branch":"main"}', b'[]', msgspec.json.encode(issue(CONTENT.body, pull=True))))
        report = sync_model.Report(1, 'updated', PINS, TARGET, ('infra/renode-pins.json',), pull_request=CONTENT)
        with tempfile.TemporaryDirectory(prefix='sync-test-') as directory, patch('upstream.git', side_effect=git):
            _ = sync_github.publish(ROOT, Path(directory) / 'worktree', report, api)
        commit = next(call for call in calls if 'commit-tree' in call)
        self.assertIn(old, commit)
        push = next(call for call in calls if call[0] == 'push')
        self.assertEqual(push, ('push', 'origin', 'c' * 40 + ':refs/heads/' + sync_model.BRANCH))


if __name__ == '__main__':
    _ = unittest.main()

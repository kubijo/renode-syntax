"""Publish checked sync proposals through typed GitHub requests and a dedicated branch."""

import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import msgspec
import upstream
from renode_model import SourceError
from sync_model import BRANCH, Content, Report

MARKER = '<!-- renode-syntax:upstream-sync -->'


class Repository(msgspec.Struct):
    default_branch: str


class PullReference(msgspec.Struct):
    url: str


class Issue(msgspec.Struct):
    number: int
    title: str
    body: str | None
    html_url: str
    pull_request: PullReference | None = None


class PullWrite(msgspec.Struct):
    title: str
    body: str
    head: str
    base: str


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is None or not token:
            raise SourceError('Publication requires a GitHub owner/repository and GITHUB_TOKEN')
        self.repository: str = repository
        self.token: str = token

    def call(self, endpoint: str, payload: msgspec.Struct | None = None, method: str = 'GET') -> bytes:
        request = urllib.request.Request(
            'https://api.github.com/' + endpoint,
            data=msgspec.json.encode(payload) if payload is not None else None,
            headers={
                'Accept': 'application/vnd.github+json',
                'Authorization': 'Bearer ' + self.token,
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'renode-syntax-sync',
                'Content-Type': 'application/json',
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise SourceError(f'GitHub {method} {endpoint}: HTTP {error.code}') from None

    def default_branch(self) -> str:
        value = msgspec.json.decode(self.call(f'repos/{self.repository}'), type=Repository)
        return value.default_branch

    def issue(self, content: Content) -> str:
        marker = content.body.splitlines()[0]
        if not marker.startswith('<!-- renode-syntax:'):
            raise SourceError('Refusing to publish an issue without a sync ownership marker')
        matches: list[Issue] = []
        for page in range(1, 101):
            entries = msgspec.json.decode(
                self.call(f'repos/{self.repository}/issues?state=open&per_page=100&page={page}'),
                type=tuple[Issue, ...],
            )
            matches.extend(item for item in entries if item.pull_request is None and marker in (item.body or ''))
            if len(entries) < 100:
                break
        else:
            raise SourceError('Too many open issues to establish sync issue ownership')
        if len(matches) > 1:
            raise SourceError('Multiple open issues have the same sync ownership marker')
        if matches:
            existing = matches[0]
            if (existing.title, existing.body) == (content.title, content.body):
                return existing.html_url
            endpoint, method = f'repos/{self.repository}/issues/{existing.number}', 'PATCH'
        else:
            endpoint, method = f'repos/{self.repository}/issues', 'POST'
        return msgspec.json.decode(self.call(endpoint, content, method), type=Issue).html_url

    def pulls(self, base: str) -> tuple[Issue, ...]:
        query = urllib.parse.urlencode({
            'state': 'open',
            'head': self.repository.split('/')[0] + ':' + BRANCH,
            'base': base,
            'per_page': 2,
        })
        pulls = msgspec.json.decode(self.call(f'repos/{self.repository}/pulls?{query}'), type=tuple[Issue, ...])
        if len(pulls) > 1 or any(MARKER not in (item.body or '') for item in pulls):
            raise SourceError('The sync branch is attached to an unowned or ambiguous pull request')
        return pulls

    def pull(self, content: Content, base: str, existing: tuple[Issue, ...]) -> str:
        if existing:
            old = existing[0]
            if (old.title, old.body) == (content.title, content.body):
                return old.html_url
            response = self.call(f'repos/{self.repository}/pulls/{old.number}', content, 'PATCH')
        else:
            response = self.call(
                f'repos/{self.repository}/pulls', PullWrite(content.title, content.body, BRANCH, base), 'POST'
            )
        return msgspec.json.decode(response, type=Issue).html_url


def publish(root: Path, workspace: Path, report: Report, api: GitHub) -> str | None:
    if report.issue is not None:
        return api.issue(report.issue)
    if report.status == 'unchanged':
        return None
    content = report.pull_request
    if report.status != 'updated' or content is None or not report.files:
        raise SourceError('Refusing to publish an incomplete or unchecked sync proposal')
    origin = upstream.git(root, 'remote', 'get-url', 'origin')
    normalized = origin.replace('git@github.com:', 'https://github.com/').removesuffix('.git')
    if normalized != 'https://github.com/' + api.repository:
        raise SourceError('The publication repository does not match origin')
    base = api.default_branch()
    existing = api.pulls(base)
    remote = upstream.git(workspace, 'ls-remote', '--heads', 'origin', f'refs/heads/{BRANCH}', network=True)
    old_head: str | None = None
    if remote:
        fields = remote.split()
        if len(fields) != 2 or fields[1] != f'refs/heads/{BRANCH}':
            raise SourceError('Unexpected sync branch advertisement')
        _ = upstream.git(workspace, 'fetch', '--quiet', '--no-tags', 'origin', f'refs/heads/{BRANCH}', network=True)
        old_head = upstream.git(workspace, 'rev-parse', 'FETCH_HEAD')
        if old_head != fields[0] or MARKER not in upstream.git(workspace, 'log', '-1', '--format=%B', old_head):
            raise SourceError('The remote sync branch changed or is not owned by this automation')
    _ = upstream.git(workspace, 'add', '--', *report.files)
    tree = upstream.git(workspace, 'write-tree')
    if old_head is None or tree != upstream.git(workspace, 'rev-parse', f'{old_head}^{{tree}}'):
        base_head = upstream.git(workspace, 'rev-parse', 'HEAD')
        parents = ('-p', base_head) + (('-p', old_head) if old_head is not None and old_head != base_head else ())
        message = workspace.parent / 'commit-message.txt'
        _ = message.write_text(content.title + '\n\n' + content.body)
        # Including the previous automation head as a parent permits a normal fast-forward
        # push. The tree still comes entirely from the current base plus checked products.
        head = upstream.git(
            workspace,
            '-c',
            'user.name=github-actions[bot]',
            '-c',
            'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit-tree',
            tree,
            *parents,
            '-F',
            str(message),
        )
        _ = upstream.git(workspace, 'push', 'origin', f'{head}:refs/heads/{BRANCH}', network=True)
    return api.pull(content, base, existing)

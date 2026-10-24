"""Exercise diagnostic failure cases without depending on the host's tools."""

import io
import sys
import tempfile
import unittest
from pathlib import Path

import checks
import msgspec
from doctor import FlakeLock, Locked, Node, Original, Pin, Report, Tool, inspect_tool, read_pins, render
from rich.console import Console


class ToolingTests(unittest.TestCase):
    def test_pin_reader_rejects_missing_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            path = Path(directory) / 'flake.lock'
            _ = path.write_bytes(msgspec.json.encode(FlakeLock(nodes={'nixpkgs': Node()})))
            with self.assertRaisesRegex(ValueError, 'missing locked revision for nixpkgs'):
                _ = read_pins(path)

    def test_pin_reader_validates_json_types(self) -> None:
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            path = Path(directory) / 'flake.lock'
            _ = path.write_bytes(b'{"nodes":{"nixpkgs":{"locked":{"rev":7}}}}')
            with self.assertRaises(msgspec.ValidationError):
                _ = read_pins(path)

    def test_pin_reader_preserves_release_and_revisions(self) -> None:
        nodes = {key: Node(Locked(key + '-rev')) for key in ('nixpkgs', 'nixpkgs-pinned')}
        nodes['nix-tools'] = Node(Locked('tools-rev'), Original('v0.10.0'))
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            path = Path(directory) / 'flake.lock'
            _ = path.write_bytes(msgspec.json.encode(FlakeLock(nodes=nodes)))
            self.assertIn(Pin('nix-tools', 'tools-rev', 'v0.10.0'), read_pins(path))

    def test_missing_tool_is_reported(self) -> None:
        report = inspect_tool(Tool('renode-tool-that-does-not-exist', 'Nix shell'))
        self.assertEqual(report.problem, 'executable not found')
        self.assertIsNone(report.location)

    def test_failed_version_command_is_reported(self) -> None:
        report = inspect_tool(Tool(sys.executable, 'host bootstrap', ('--invalid-tooling-option',)))
        self.assertEqual(report.problem, 'version command failed')

    def test_check_failure_keeps_diagnostics_and_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            root = Path(directory)
            console = Console(file=io.StringIO())
            status = checks.run(
                root,
                console,
                'failed',
                (
                    sys.executable,
                    '-m',
                    'unittest',
                    'renode_missing_test_module',
                ),
            )
            self.assertEqual(status, 1)
            self.assertIn('renode_missing_test_module', (root / '.tmp/checks/failed.log').read_text())

    def test_plan_stops_after_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            root = Path(directory)
            planfile = root / 'plan.json'
            plan = checks.Plan((
                checks.Step('failed', (sys.executable, '--invalid-tooling-option')),
                checks.Step('skipped', (sys.executable, '--version')),
            ))
            _ = planfile.write_bytes(msgspec.json.encode(plan))
            status = checks.execute_plan(root, Console(file=io.StringIO()), planfile, ())
            self.assertNotEqual(status, 0)
            self.assertFalse((root / '.tmp/checks/skipped.log').exists())

    def test_plan_forwards_arguments_to_the_declared_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix='tooling-test-') as directory:
            root = Path(directory)
            planfile = root / 'plan.json'
            plan = checks.Plan((checks.Step('version', (sys.executable,), forward_arguments=True),))
            _ = planfile.write_bytes(msgspec.json.encode(plan))
            status = checks.execute_plan(root, Console(file=io.StringIO()), planfile, ('--version',))
            self.assertEqual(status, 0)
            self.assertIn('Python 3.15', (root / '.tmp/checks/version.log').read_text())

    def test_rich_colors_terminal_and_keeps_plain_record(self) -> None:
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=True, color_system='standard', record=True, width=120)
        report = Report('example', '1.2.3', Path('/nix/store/example/bin/example'), 'Nix shell')
        render(console, (), (report,))
        self.assertIn('\x1b[', stream.getvalue())
        self.assertNotIn('\x1b[', console.export_text(clear=False))
        self.assertIn('/nix/store/example/bin/example', console.export_text())

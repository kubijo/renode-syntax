"""Verify corpus enumeration, exact blob framing, and isolated pinned materialization."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import msgspec
import upstream
from corpus import Manifest, blob_id, parse_blobs, prepare
from renode_model import Pin, Pins, SourceError
from rich.console import Console


def framed(content: bytes) -> bytes:
    return f'{blob_id(content)} blob {len(content)}\n'.encode() + content + b'\n'


class CorpusTests(unittest.TestCase):
    def test_tree_lists_both_languages_without_following_submodules(self) -> None:
        output = (
            '100644 blob ' + 'a' * 40 + '\tplatforms/test board.repl\0'
            '160000 commit ' + 'b' * 40 + '\tsrc/Infrastructure\0'
            '100644 blob ' + 'c' * 40 + '\tscripts/start.resc\0'
            '100644 blob ' + 'd' * 40 + '\tscripts/helper.py\0'
        )
        files = upstream.parse_corpus_tree(output)
        self.assertEqual([file.path for file in files], ['platforms/test board.repl', 'scripts/start.resc'])

    def test_tree_rejects_unsafe_or_nonregular_corpus_entries(self) -> None:
        for mode, path in (
            ('120000', 'link.repl'),
            ('100644', '../outside.resc'),
            ('100644', '/outside.repl'),
            ('100644', 'bad\nname.resc'),
        ):
            with self.subTest(path=path), self.assertRaises(SourceError):
                _ = upstream.parse_corpus_tree(f'{mode} blob {"a" * 40}\t{path}\0')
        with self.assertRaisesRegex(SourceError, 'Truncated'):
            _ = upstream.parse_corpus_tree(f'100644 blob {"a" * 40}\ta.repl')
        duplicate = f'100644 blob {"a" * 40}\ta.repl\0'
        with self.assertRaisesRegex(SourceError, 'duplicate'):
            _ = upstream.parse_corpus_tree(duplicate + duplicate)

    def test_sparse_checkout_escapes_literal_glob_characters(self) -> None:
        self.assertEqual(upstream.sparse_pattern('platforms/board[1].repl'), r'/platforms/board\[1\].repl')

    def test_blob_stream_obeys_byte_sizes_and_exact_object_ids(self) -> None:
        contents = (b'line\nwith\0binary framing\r\n', 'echo é'.encode(), b'')
        entries = tuple(
            upstream.CorpusFile(f'{index}.resc', blob_id(content)) for index, content in enumerate(contents)
        )
        self.assertEqual(parse_blobs(b''.join(framed(content) for content in contents), entries), contents)

    def test_missing_truncated_corrupt_and_trailing_blobs_fail(self) -> None:
        content = b'echo 1\n'
        entry = (upstream.CorpusFile('test.resc', blob_id(content)),)
        for output in (
            b'',
            f'{entry[0].blob} missing\n'.encode(),
            framed(content)[:-2],
            framed(content).replace(content, b'echo 2\n'),
            framed(content) + b'extra',
        ):
            with self.subTest(output=output), self.assertRaises(SourceError):
                _ = parse_blobs(output, entry)

    def test_preparation_rebuilds_only_files_in_the_pinned_manifest(self) -> None:
        pin = Pin('https://github.com/renode/renode.git', 'a' * 40, ('LICENSE',))
        pins = Pins(pin, pin)
        contents = (b'device: Example.Device @ sysbus 0\n', b'echo 1\n')
        entries = tuple(
            upstream.CorpusFile(name, blob_id(content))
            for name, content in zip(('board.repl', 'start.resc'), contents, strict=True)
        )
        with tempfile.TemporaryDirectory(prefix='corpus-test-') as directory:
            root = Path(directory)
            with (
                patch('upstream.read_pins', return_value=pins),
                patch('upstream.validate', return_value=()),
                patch('upstream.corpus_files', side_effect=[entries, ()]),
                patch('corpus.read_blobs', side_effect=[contents, ()]),
            ):
                first = prepare(root, Console(file=io.StringIO()))
            target = root / first.files[0].file
            _ = target.write_bytes(b'modified')
            _ = (target.parent / 'untracked.resc').write_bytes(b'not a pinned input')
            with (
                patch('upstream.read_pins', return_value=pins),
                patch('upstream.validate', return_value=()),
                patch('upstream.corpus_files', side_effect=[entries, ()]),
                patch('corpus.read_blobs', side_effect=[contents, ()]),
            ):
                second = prepare(root, Console(file=io.StringIO()))
            self.assertEqual(first, second)
            self.assertEqual(target.read_bytes(), contents[0])
            saved = msgspec.json.decode((root / '.tmp/corpus/manifest.json').read_bytes(), type=Manifest)
            self.assertEqual(saved, second)
            listed = (root / '.tmp/corpus/files0').read_bytes().split(b'\0')[:-1]
            self.assertEqual(listed, [item.file.encode() for item in saved.files])
            self.assertEqual(len(saved.files), 2)

    def test_empty_or_single_language_corpus_cannot_pass(self) -> None:
        pin = Pin('https://github.com/renode/renode.git', 'a' * 40, ('LICENSE',))
        cases = (
            ((), (), 'no .repl inputs'),
            ((upstream.CorpusFile('board.repl', blob_id(b'')),), (b'',), 'no .resc inputs'),
        )
        for entries, contents, problem in cases:
            with (
                tempfile.TemporaryDirectory(prefix='corpus-test-') as directory,
                patch('upstream.read_pins', return_value=Pins(pin, pin)),
                patch('upstream.validate', return_value=()),
                patch('upstream.corpus_files', return_value=entries),
                patch('corpus.read_blobs', return_value=contents),
                self.assertRaisesRegex(SourceError, problem),
            ):
                _ = prepare(Path(directory), Console(file=io.StringIO()))

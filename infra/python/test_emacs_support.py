"""Guard repeatable preparation from immutable grammar inputs."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emacs_support import Arguments, prepare

ROOT = Path(__file__).resolve().parents[2]


class EmacsPreparationTests(unittest.TestCase):
    def test_preparation_is_repeatable_with_a_read_only_python_grammar(self) -> None:
        directory = ROOT / '.tmp/emacs/tooling-tests'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            root = Path(temporary)
            grammar = root / 'parser.so'
            _ = grammar.write_bytes(b'parser')
            grammar.chmod(0o444)
            fixture = root / 'infra/zed/review.repl'
            fixture.parent.mkdir(parents=True)
            _ = fixture.write_text('device:\n')
            with patch('emacs_support.build', return_value=grammar):
                prepare(root, Arguments(grammar))
                prepare(root, Arguments(grammar))
            python = root / '.tmp/emacs/grammars/libtree-sitter-python.so'
            self.assertTrue(python.is_symlink())
            self.assertEqual(python.read_bytes(), b'parser')
            self.assertEqual((root / '.tmp/emacs/review.repl').read_bytes(), fixture.read_bytes())


if __name__ == '__main__':
    _ = unittest.main()

"""Guard consumer rewrites, structural scopes and Zed query boundaries."""

import unittest
from pathlib import Path
from typing import ClassVar

from csharp_source import text, walk
from regex_source import RegexParser
from render_treesitter import content_pattern, framed, rust_pattern
from renode_model import SourceError
from tree_sitter import Query, QueryCursor, Tree
from treesitter import Grammar, build, load, problems, queries

ROOT = Path(__file__).resolve().parents[2]


class TranslationTests(unittest.TestCase):
    def test_unsupported_assertions_and_lazy_policies_require_review(self) -> None:
        for pattern in ('^x(?!y)', '^x(?=y)', '^x.*?y', '^x.+?y'):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(SourceError, 'explicit rewrite'):
                _ = rust_pattern(RegexParser(pattern).parse())

    def test_singleline_and_unicode_are_rendered_for_rust_regex(self) -> None:
        self.assertEqual(rust_pattern(RegexParser(r'^\d.').parse(), True), r'\p{Nd}(?s:.)')

    def test_delimiter_rewrite_rejects_new_shapes(self) -> None:
        self.assertEqual(framed(RegexParser('^`.*?`').parse())[0], '`')
        for pattern in ('^begin.*?end', '^`.*?~', '^`.*?`x'):
            with self.subTest(pattern=pattern), self.assertRaises(SourceError):
                _ = framed(RegexParser(pattern).parse())
        with self.assertRaises(SourceError):
            _ = content_pattern('END')


class GrammarTests(unittest.TestCase):
    grammar: ClassVar[Grammar]

    @classmethod
    def setUpClass(cls) -> None:
        cls.grammar = load(build(ROOT))
        queries(ROOT, cls.grammar)

    def parse(self, source: str) -> Tree:
        tree = self.grammar.parse(source.encode())
        self.assertFalse(tree.root_node.has_error, str(tree.root_node))
        self.assertEqual(problems(tree.root_node), ())
        return tree

    def captures(self, query: str, source: str) -> dict[str, list[str]]:
        tree = self.parse(source)
        compiled = Query(self.grammar.language, (ROOT / 'zed/languages/resc' / query).read_text())
        return {
            name: [text(node) for node in sorted(nodes, key=lambda node: node.start_byte)]
            for name, nodes in QueryCursor(compiled).captures(tree.root_node).items()
        }

    def test_upstream_first_match_beats_longest_token(self) -> None:
        tree = self.parse('echo trueSuffix nullSuffix ١٢٣ 0xAf -2e+3\n')
        self.assertEqual([text(node) for node in walk(tree.root_node, 'boolean')], ['true'])
        self.assertEqual([text(node) for node in walk(tree.root_node, 'null')], ['null'])
        self.assertEqual([text(node) for node in walk(tree.root_node, 'number')], ['١٢٣', '0xAf', '-2e+3'])

    def test_commands_have_boundaries_and_aliases_remain_ordinary(self) -> None:
        source = 'echoer echo\np arg\necho "ok"\n'
        captures = self.captures('highlights.scm', source)
        self.assertEqual(captures['keyword'], ['echo'])
        self.assertNotIn('echoer', captures['keyword'])
        self.assertNotIn('p', captures['keyword'])
        tree = self.parse(source)
        self.assertEqual(len(tuple(walk(tree.root_node, 'command'))), 3)

    def test_multiline_macro_contains_monitor_statements(self) -> None:
        source = 'macro reset\n"""\n$pc = `cpu PC`\nsysbus LoadELF $bin\n"""\n'
        tree = self.parse(source)
        self.assertEqual(len(tuple(walk(tree.root_node, 'macro_definition'))), 1)
        self.assertEqual(len(tuple(walk(tree.root_node, 'assignment'))), 1)
        self.assertEqual(len(tuple(walk(tree.root_node, 'execution'))), 1)
        self.assertEqual(self.captures('outline.scm', source)['name'], ['reset'])

    def test_python_injection_excludes_delimiters_and_other_multiline_strings(self) -> None:
        source = 'python """\nprint("hello")\n"""\nset script\n"""\nprint("opaque")\n"""\n'
        captures = self.captures('injections.scm', source)
        self.assertEqual(captures['injection.content'], ['\nprint("hello")\n'])
        query = Query(self.grammar.language, (ROOT / 'zed/languages/resc/injections.scm').read_text())
        self.assertEqual(query.pattern_settings(0)['injection.language'], 'python')

    def test_paths_named_arguments_comments_and_crlf(self) -> None:
        source = '# comment\r\ninclude $ORIGIN/../a.resc\r\ncpu Trace path=@a\\ b enabled=True\r\necho topic:name; :tail\r\n'
        tree = self.parse(source)
        self.assertEqual([text(node) for node in walk(tree.root_node, 'variable_path')], ['$ORIGIN/../a.resc'])
        self.assertEqual(len(tuple(walk(tree.root_node, 'named_argument'))), 2)
        self.assertEqual([text(node) for node in walk(tree.root_node, 'comment')], ['# comment\r', ':tail\r'])

    def test_backticks_bound_the_raw_body_before_inner_tokenization(self) -> None:
        source = 'echo `echo "quoted"` `# comment` `echo "`\n'
        tree = self.parse(source)
        expected = ['echo "quoted"', '# comment', 'echo "']
        self.assertEqual([text(node) for node in walk(tree.root_node, 'execution_body')], expected)
        self.assertEqual(self.captures('injections.scm', source)['injection.content'], expected)

    def test_missing_and_invalid_input_cannot_pass_the_corpus_gate(self) -> None:
        for source in ('echo `cpu PC', 'echo [1', 'python """unclosed', 'macro reset\n"""\necho x', 'echo %', '$ = 1'):
            with self.subTest(source=source):
                self.assertTrue(problems(self.grammar.parse(source.encode()).root_node))


if __name__ == '__main__':
    _ = unittest.main()

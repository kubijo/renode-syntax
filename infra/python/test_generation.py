"""Exercise registration boundaries and translations with small independent source fixtures."""

import io
import re
import tempfile
import unittest
from pathlib import Path

import msgspec
from csharp_source import parse
from extract_commands import command_name, csharp_commands, python_commands
from extract_platform import Platform
from extract_tokens import tokenizer
from generate import synchronize
from regex_source import translate
from render_sublime import render
from renode_model import Pin, Pins, SourceError
from rich.console import Console
from upstream import read_pins

COMMAND = """
namespace Example {
    // base(monitor, "decoy", "not a registration")
    class ConstantCommand : AutoLoadCommand {
        const string FullName = "actual";
        public ConstantCommand(Monitor monitor) : base(monitor, FullName, "description", "a") {}
    }
    class GenericCommand : Command {
        public GenericCommand(Monitor monitor, string name) : base(monitor, name, "description") {}
    }
}
"""
MONITOR = """
class Monitor {
    void InitCommands() {
        var command = new GenericCommand(this, "boundName");
        Commands.Add(command);
    }
    void RegisterCommand(Command command) { Commands.Add(command); }
}
"""


class GenerationTests(unittest.TestCase):
    def command_names(self, commands: str = COMMAND, monitor: str = MONITOR) -> list[str]:
        return [
            item.name
            for item in csharp_commands(
                (parse('infrastructure', 'Commands.cs', commands.encode()),),
                parse('infrastructure', 'Monitor.cs', monitor.encode()),
            )
        ]

    def test_constants_and_constructor_parameters_are_resolved(self) -> None:
        self.assertEqual(self.command_names(), ['actual', 'boundName'])

    def test_constant_name_provenance_points_to_its_definition(self) -> None:
        commands = csharp_commands(
            (parse('infrastructure', 'Commands.cs', COMMAND.encode()),),
            parse('infrastructure', 'Monitor.cs', MONITOR.encode()),
        )
        self.assertEqual(commands[0].source.line, 5)
        self.assertEqual(commands[1].source.path, 'Monitor.cs')
        self.assertIsNotNone(commands[1].definition)

    def test_short_aliases_and_commented_registrations_are_excluded(self) -> None:
        self.assertNotIn('a', self.command_names())
        self.assertNotIn('decoy', self.command_names())

    def test_computed_constructor_names_require_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'constant'):
            _ = self.command_names(COMMAND.replace('base(monitor, FullName,', 'base(monitor, GetName(),'))

    def test_computed_monitor_names_require_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'constant'):
            _ = self.command_names(monitor=MONITOR.replace('"boundName"', 'GetName()'))

    def test_unknown_monitor_registration_site_requires_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'registration site'):
            _ = self.command_names(monitor=MONITOR.replace('void RegisterCommand', 'void NewRegistrationAPI'))

    def test_unresolved_constructor_parameters_require_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'Uninstantiated'):
            _ = self.command_names(monitor=MONITOR.replace('Commands.Add(command);', '', 1))

    def test_conditional_monitor_registration_requires_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'registration statement'):
            _ = self.command_names(
                monitor=MONITOR.replace('Commands.Add(command);', 'if (enabled) Commands.Add(command);', 1)
            )

    def test_new_registration_api_requires_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'registration statement'):
            _ = self.command_names(monitor=MONITOR.replace('Commands.Add(command);', 'Commands.AddRange(command);', 1))

    def test_invalid_csharp_fails_before_extraction(self) -> None:
        with self.assertRaisesRegex(SourceError, 'parse error'):
            _ = parse('renode', 'Broken.cs', b'class Broken {')

    def test_ironpython_print_statements_are_parsed_without_execution(self) -> None:
        source = (
            '# def mc_decoy(): pass\ndef mc_echo(value):\n    print value,\n    raise Exception("never executed")\n'
        )
        commands = python_commands(source)
        self.assertEqual([item.name for item in commands], ['echo'])
        self.assertEqual(commands[0].source.line, 2)

    def test_nested_python_commands_require_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'conditional/nested'):
            _ = python_commands('if True:\n    def mc_local(): pass\n')

    def test_assigned_python_commands_require_review(self) -> None:
        with self.assertRaisesRegex(SourceError, 'assigned command'):
            _ = python_commands('mc_alias = some_callable\n')

    def test_nonliteral_keyword_fails(self) -> None:
        source = b'class Grammar { static Parser<string> Keyword = MakeKeyword(GetName()); }'
        with self.assertRaisesRegex(SourceError, 'constant'):
            _ = Platform(parse('renode', 'Grammar.cs', source)).keywords()

    def test_keyword_names_come_from_arguments_not_field_names(self) -> None:
        source = b'class Grammar { static Parser<string> ChangedKeyword = MakeKeyword("upstream"); }'
        keywords = Platform(parse('renode', 'Grammar.cs', source)).keywords()
        self.assertEqual(keywords[0].name, 'upstream')
        self.assertEqual(keywords[0].symbol, 'ChangedKeyword')

    def test_token_order_flags_and_whitespace_factory_are_preserved(self) -> None:
        source = rb"""class Tokenizer {
            static Tokenizer CreateTokenizer() {
                tokenizer.AddToken(new Regex(@"^a.b", RegexOptions.Singleline), x => new FirstToken(x));
                tokenizer.AddToken(new Regex(@"^\s+"), x => null);
            }
        }"""
        rules = tokenizer(parse('infrastructure', 'Tokenizer.cs', source))
        self.assertEqual([(rule.order, rule.kind) for rule in rules], [(0, 'FirstToken'), (1, 'Whitespace')])
        self.assertEqual(rules[0].options, ('Singleline',))
        self.assertEqual(rules[0].javascript, r'a[\s\S]b')

    def test_unknown_token_factory_requires_review(self) -> None:
        source = rb'class Tokenizer { static void CreateTokenizer() { tokenizer.AddToken(new Regex(@"^a"), x => MakeToken(x)); } }'
        with self.assertRaisesRegex(SourceError, 'factory body'):
            _ = tokenizer(parse('infrastructure', 'Tokenizer.cs', source))

    def test_conditional_token_rules_require_review(self) -> None:
        source = rb'class Tokenizer { static void CreateTokenizer() { if (enabled) tokenizer.AddToken(new Regex(@"^a"), x => new Token(x)); } }'
        with self.assertRaisesRegex(SourceError, 'registration statement'):
            _ = tokenizer(parse('infrastructure', 'Tokenizer.cs', source))

    def test_inline_case_flag_is_expanded_for_both_consumers(self) -> None:
        sublime, javascript = translate(r'^0x([0-9]|(?i:[a-f]))+')
        self.assertNotIn('(?i:', javascript)
        self.assertEqual(sublime, javascript)
        self.assertIsNotNone(re.fullmatch(sublime, '0xA0f'))
        self.assertIsNone(re.fullmatch(sublime, '0xg'))

    def test_javascript_unicode_classes_keep_dotnet_word_and_digit_categories(self) -> None:
        self.assertEqual(translate(r'^\d+')[1], r'\p{Nd}+')
        self.assertEqual(translate(r'^[\w.]+')[1], r'[\p{L}\p{Mn}\p{Nd}\p{Pc}.]+')

    def test_unknown_regex_constructs_and_options_require_review(self) -> None:
        for pattern in (r'^(?<name>x)', r'^x\1', r'^(?i:é)', r'^[a-z-[d]]', r'^x{3,1}', r'x', r'^[x'):
            with self.subTest(pattern=pattern), self.assertRaises(SourceError):
                _ = translate(pattern)
        with self.assertRaisesRegex(SourceError, 'RegexOptions'):
            _ = translate('^x', ('IgnoreCase',))

    def test_templates_leave_native_sublime_variables_untouched(self) -> None:
        self.assertEqual(render('{{ident}} @@KEY@@', {'KEY': 'derived'}), '{{ident}} derived')
        with self.assertRaisesRegex(SourceError, 'Unknown template'):
            _ = render('@@MISSING@@', {})

    def test_generation_check_detects_stale_files_without_overwriting_them(self) -> None:
        with tempfile.TemporaryDirectory(prefix='generation-test-') as directory:
            root = Path(directory)
            expected = {'generated/example.json': b'new\n'}
            console = Console(file=io.StringIO())
            self.assertEqual(synchronize(root, expected, False, console), 0)
            self.assertEqual(synchronize(root, expected, True, console), 0)
            _ = (root / 'generated/example.json').write_bytes(b'old\n')
            self.assertEqual(synchronize(root, expected, True, console), 1)
            self.assertEqual((root / 'generated/example.json').read_bytes(), b'old\n')
            self.assertIn('+new', (root / '.tmp/generation/example.json.diff').read_text())

    def test_pin_file_validates_revisions_paths_and_types(self) -> None:
        with tempfile.TemporaryDirectory(prefix='generation-test-') as directory:
            root = Path(directory)
            (root / 'infra').mkdir()
            path = root / 'infra/renode-pins.json'
            for revision, paths in (('HEAD', ('LICENSE',)), ('a' * 40, ('../outside',)), ('a' * 40, ('/absolute',))):
                pin = Pin('https://github.com/renode/renode.git', revision, paths)
                _ = path.write_bytes(msgspec.json.encode(Pins(pin, pin)))
                with self.assertRaises(SourceError):
                    _ = read_pins(root)
            _ = path.write_bytes(b'{"renode":7}')
            with self.assertRaises(msgspec.ValidationError):
                _ = read_pins(root)

    def test_command_names_reject_pattern_injection(self) -> None:
        with self.assertRaisesRegex(SourceError, 'full command name'):
            _ = command_name('name|other')

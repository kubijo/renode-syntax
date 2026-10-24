const derived = require('../../generated/resc.json');

function lexical(kind, index = 0) {
    const rule = derived.rules[kind][index];
    return token(prec(rule.priority, new RustRegex(rule.pattern)));
}

function command(name) {
    if (!derived.commands.includes(name)) throw new Error(`Unknown upstream command: ${name}`);
    return token(prec(derived.rules.LiteralToken[0].priority, name));
}

function statements($, statement = $._statement) {
    return seq(repeat(seq(optional(statement), $._separator)), optional(statement));
}

module.exports = grammar({
    name: 'resc',
    extras: $ => [new RustRegex(derived.inline_space), $.comment],
    rules: {
        source_file: $ => statements($),
        _separator: $ => choice($._newline, $.command_split),
        _newline: _ => /\r?\n/,
        _statement: $ => choice($.assignment, $.macro_definition, $.python_command, $.command),
        assignment: $ => prec.right(seq(field('name', $.variable), $.assignment_operator, repeat1($._argument))),
        assignment_operator: _ => choice(lexical('EqualityToken'), lexical('ConditionalEqualityToken')),
        command: $ => prec.right(seq(field('name', $.literal), repeat($._argument))),
        macro_keyword: _ => command('macro'),
        python_keyword: _ => command('python'),
        macro_definition: $ => prec(2, seq($.macro_keyword, field('name', choice($.literal, $.string)), $.macro_body)),
        macro_body: $ =>
            prec(
                2,
                seq(
                    field('open', $._multiline_open),
                    statements($, $._macro_statement),
                    field('close', $.multiline_delimiter),
                ),
            ),
        _macro_statement: $ =>
            choice(
                alias($._inline_command, $.command),
                alias($._inline_assignment, $.assignment),
                alias($._inline_python, $.python_command),
            ),
        _inline_command: $ => prec.right(seq(field('name', $.literal), repeat($._inline_argument))),
        _inline_assignment: $ =>
            prec.right(seq(field('name', $.variable), $.assignment_operator, repeat1($._inline_argument))),
        _inline_python: $ => prec.right(seq($.python_keyword, repeat($._inline_argument))),
        python_command: $ => prec(2, seq($.python_keyword, choice($.python_block, repeat($._inline_argument)))),
        python_block: $ => prec(2, seq($._multiline_open, optional($.python_body), $.multiline_delimiter)),
        python_body: _ => prec(2, token(new RustRegex(derived.multiline_content))),
        multiline_string: $ => seq($._multiline_open, optional($.string_content), $.multiline_delimiter),
        _multiline_open: $ =>
            choice(
                $.multiline_delimiter,
                alias(
                    token(
                        prec(
                            20,
                            new RustRegex('\\r?\\n(?:' + derived.inline_space + ')?' + derived.multiline_delimiter),
                        ),
                    ),
                    $.multiline_delimiter,
                ),
            ),
        string_content: _ => token(prec(-1, new RustRegex(derived.multiline_content))),
        multiline_delimiter: _ => lexical('MultilineStringTerminatorToken'),
        _argument: $ => choice($.multiline_string, $._inline_argument),
        _inline_argument: $ =>
            choice(
                $.named_argument,
                $.literal,
                $.variable,
                $.variable_path,
                $.string,
                $.path,
                $.number,
                $.boolean,
                $.null,
                $.range,
                $.execution,
                $.list,
                $.comma,
            ),
        named_argument: $ =>
            prec.right(seq(field('name', $.literal), lexical('EqualityToken'), field('value', $._inline_argument))),
        execution: $ =>
            seq(
                field('open', $.execution_delimiter),
                optional($.execution_body),
                field('close', $.execution_delimiter),
            ),
        // Renode closes execution at the first backtick, even inside quoted text.
        // Parse its captured body through a resc injection without changing that boundary.
        execution_body: _ =>
            token.immediate(prec(derived.rules.CommentToken[0].priority + 1, new RustRegex(derived.execution_content))),
        execution_delimiter: _ => token(prec(derived.rules.ExecutionToken[0].priority, derived.execution_delimiter)),
        list: $ => seq($.left_bracket, repeat($._inline_argument), $.right_bracket),
        left_bracket: _ => lexical('LeftBraceToken'),
        right_bracket: _ => lexical('RightBraceToken'),
        string: _ => choice(lexical('StringToken', 0), lexical('StringToken', 1)),
        literal: _ => lexical('LiteralToken'),
        variable: _ => lexical('VariableToken'),
        // Monitor.Tokenize retries failed variable-plus-path input after expansion.
        variable_path: $ => seq($.variable, token.immediate(new RustRegex(derived.path_suffix))),
        path: _ => lexical('PathToken'),
        number: _ =>
            choice(
                lexical('HexToken'),
                lexical('TimeIntervalToken'),
                lexical('FloatToken'),
                lexical('DecimalIntegerToken'),
            ),
        boolean: _ => lexical('BooleanToken'),
        null: _ => lexical('NullToken'),
        range: _ => choice(lexical('AbsoluteRangeToken'), lexical('RelativeRangeToken')),
        comma: _ => lexical('CommaToken'),
        command_split: _ => lexical('CommandSplit'),
        comment: _ => choice(lexical('CommentToken', 0), lexical('CommentToken', 1)),
    },
});

const derived = require('../../generated/repl.json');
const symbol = name => derived.symbols[name].value;
const keyword = name => derived.keywords[name].name;
const pattern = name => new RustRegex(derived.rules[name].pattern);
const separated = (rule, separator) => seq(rule, repeat(seq(separator, rule)));

module.exports = grammar({
    name: 'repl',
    externals: $ => [
        $.block_start,
        $.block_end,
        $._separator,
        $.comment,
        $._space,
        $.string_content,
        $.string_end,
        $.multiline_content,
        $.multiline_end,
        $.monitor_text,
        $._line_start,
        $._error_sentinel,
    ],
    extras: $ => [$._space, $.comment, $._line_start],
    rules: {
        source_file: $ =>
            seq(
                repeat(seq($.using, repeat($._separator))),
                optional(seq(separated($.entry, repeat1($._separator)), repeat($._separator))),
            ),
        using: $ => seq(keyword('UsingKeyword'), field('path', $.string)),
        entry: $ =>
            seq(
                optional(keyword('LocalKeyword')),
                field('name', $.identifier),
                symbol('Colon'),
                optional(field('type', $.type_name)),
                optional($.registration),
                optional($.alias),
                optional($.attributes),
            ),
        alias: $ => seq(keyword('AsKeyword'), $.string),
        type_name: $ => separated($.identifier, symbol('Dot')),
        identifier: _ => token(pattern('Identifier')),
        registration: $ =>
            seq(
                symbol('AtSign'),
                choice(
                    keyword('NoneKeyword'),
                    $.registration_item,
                    seq(
                        $.block_start,
                        separated($.registration_item, $._separator),
                        optional($._separator),
                        $.block_end,
                    ),
                ),
            ),
        registration_item: $ => prec.right(seq(field('bus', $.reference), optional(field('point', $._non_dict_value)))),
        attributes: $ =>
            seq(
                $.block_start,
                optional(seq(separated($._attribute, $._separator), optional($._separator))),
                $.block_end,
            ),
        _attribute: $ => choice($.property, $.monitor, $.irq),
        property: $ =>
            seq(
                field('name', $.identifier),
                symbol('Colon'),
                field(
                    'value',
                    choice($._value, alias(keyword('NoneKeyword'), $.none), alias(keyword('EmptyKeyword'), $.empty)),
                ),
            ),
        monitor: $ =>
            seq(
                field('kind', $.monitor_keyword),
                optional($.monitor_modifier),
                symbol('Colon'),
                $.block_start,
                optional(field('body', $.monitor_body)),
                $.block_end,
            ),
        monitor_keyword: _ => choice(keyword('PreinitKeyword'), keyword('InitKeyword'), keyword('ResetKeyword')),
        monitor_body: $ => repeat1($.monitor_text),
        monitor_modifier: _ => new RustRegex(derived.monitor_suffix.pattern),
        _value: $ => choice($._non_dict_value, $.dictionary),
        _non_dict_value: $ => choice($._scalar, $.object, $.list),
        _scalar: $ => choice($.string, $.multiline_string, $.range, $.number, $.enum, $.boolean, $.reference),
        reference: $ => $.identifier,
        object: $ => prec.right(seq(keyword('NewKeyword'), field('type', $.type_name), optional($.attributes))),
        list: $ =>
            seq(
                symbol('OpeningSquareBracket'),
                optional(
                    seq(
                        separated(choice($._value, alias(keyword('EmptyKeyword'), $.empty)), symbol('Comma')),
                        optional(symbol('Comma')),
                    ),
                ),
                symbol('ClosingSquareBracket'),
            ),
        dictionary: $ =>
            seq($.block_start, optional(seq(separated($.pair, $._separator), optional($._separator))), $.block_end),
        pair: $ => seq(field('key', $._scalar), symbol('Colon'), field('value', $._value)),
        enum: $ =>
            choice(seq(symbol('Dot'), $.identifier), seq($.identifier, repeat1(seq(symbol('Dot'), $.identifier)))),
        boolean: _ =>
            choice(...['TrueKeyword', 'TrueKeywordTitleCase', 'FalseKeyword', 'FalseKeywordTitleCase'].map(keyword)),
        number: _ => token(pattern('Number')),
        unsigned: _ => token(choice(pattern('HexadecimalUnsignedLong'), pattern('DecimalUnsignedLong'))),
        range: $ =>
            seq(
                symbol('OpeningChevron'),
                $.unsigned,
                symbol('Comma'),
                optional(symbol('PlusSign')),
                $.unsigned,
                symbol('ClosingChevron'),
            ),
        irq: $ =>
            seq(
                optional(choice($._source_end, $.irq_sources)),
                symbol('RightArrow'),
                choice(
                    alias(keyword('NoneKeyword'), $.none),
                    seq($.irq_destination, repeat(seq(optional(symbol('MultiplexSign')), $.irq_destination))),
                ),
            ),
        _source_end: $ => choice($.irq_range, $.unsigned, $.identifier),
        _destination_end: $ => choice($.irq_range, $.unsigned),
        irq_range: $ => seq($.unsigned, symbol('Minus'), $.unsigned),
        irq_sources: $ =>
            seq(
                symbol('OpeningSquareBracket'),
                separated($._source_end, symbol('Comma')),
                symbol('ClosingSquareBracket'),
            ),
        irq_destination: $ =>
            seq(
                field('device', $.identifier),
                optional(seq(symbol('Hash'), field('index', $.unsigned))),
                symbol('AtSign'),
                choice(
                    $._destination_end,
                    seq(
                        symbol('OpeningSquareBracket'),
                        separated($._destination_end, symbol('Comma')),
                        symbol('ClosingSquareBracket'),
                    ),
                ),
            ),
        string: $ => seq(derived.quote.value, optional($.string_content), $.string_end),
        multiline_string: $ => seq(derived.multiquote.value, optional($.multiline_content), $.multiline_end),
    },
});

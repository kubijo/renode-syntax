/* Renode's PreLexer.cs layout and delimiter behavior, adapted to incremental scanning.
 * Mechanical constants are generated from the pinned C# syntax trees. */
#include "scanner-config.h"
#include "tree_sitter/parser.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum Token {
    OPEN,
    CLOSE,
    SEPARATOR,
    COMMENT,
    SPACE,
    STRING_CONTENT,
    STRING_END,
    MULTILINE_CONTENT,
    MULTILINE_END,
    MONITOR_TEXT,
    LINE_START,
    ERROR_SENTINEL
};

typedef struct {
    uint32_t indent;
    uint32_t braces;
    uint32_t leading;
    uint32_t space_column;
    bool bol;
    bool started;
    bool opened;
    bool prefix;
    bool previous_space;
    bool physical_open;
} Scanner;

static void reset(Scanner *s) {
    memset(s, 0, sizeof(*s));
    s->bol = true;
    s->prefix = true;
}

void *tree_sitter_repl_external_scanner_create(void) {
    Scanner *s = calloc(1, sizeof(Scanner));
    reset(s);
    return s;
}

void tree_sitter_repl_external_scanner_destroy(void *payload) { free(payload); }

unsigned tree_sitter_repl_external_scanner_serialize(void *payload, char *buffer) {
    _Static_assert(sizeof(Scanner) <= TREE_SITTER_SERIALIZATION_BUFFER_SIZE, "scanner state is too large");
    memcpy(buffer, payload, sizeof(Scanner));
    return sizeof(Scanner);
}

void tree_sitter_repl_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
    Scanner *s = payload;
    reset(s);
    if (length == sizeof(Scanner))
        memcpy(s, buffer, length);
}

static void advance(TSLexer *lexer) { lexer->advance(lexer, false); }
static bool newline(int32_t ch) { return ch == '\n'; }
static bool horizontal(int32_t ch) { return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\v' || ch == '\f'; }

static bool string_token(TSLexer *lexer, bool multiline) {
    const int32_t quote = multiline ? REPL_MULTI_QUOTE : REPL_QUOTE;
    const unsigned width = multiline ? REPL_MULTI_WIDTH : 1;
    unsigned escapes = 0;
    bool content = false;
    while (!lexer->eof(lexer)) {
        if (!multiline && newline(lexer->lookahead))
            break;
        lexer->mark_end(lexer);
        if (lexer->lookahead == quote && escapes % 2 == 0) {
            unsigned count = 0;
            while (count < width && lexer->lookahead == quote) {
                advance(lexer);
                count++;
            }
            if (count == width) {
                if (content) {
                    lexer->result_symbol = multiline ? MULTILINE_CONTENT : STRING_CONTENT;
                } else {
                    lexer->mark_end(lexer);
                    lexer->result_symbol = multiline ? MULTILINE_END : STRING_END;
                }
                return true;
            }
            content = true;
            escapes = 0;
            continue;
        }
        escapes = lexer->lookahead == REPL_ESCAPE ? escapes + 1 : 0;
        advance(lexer);
        content = true;
    }
    if (content) {
        lexer->mark_end(lexer);
        lexer->result_symbol = multiline ? MULTILINE_CONTENT : STRING_CONTENT;
    }
    return content;
}

/* The slash has already been consumed. Comment syntax belongs to the platform,
 * including inside monitor bodies: injections capture only MONITOR_TEXT ranges. */
static bool comment_token(Scanner *s, TSLexer *lexer, bool allowed_line, bool first) {
    if (lexer->lookahead == REPL_SLASH && allowed_line) {
        while (!lexer->eof(lexer) && !newline(lexer->lookahead))
            advance(lexer);
        lexer->mark_end(lexer);
        lexer->result_symbol = COMMENT;
        return true;
    }
    if (lexer->lookahead != REPL_STAR)
        return false;
    advance(lexer);
    int32_t previous = 0;
    bool multiline = false;
    while (!lexer->eof(lexer)) {
        int32_t ch = lexer->lookahead;
        advance(lexer);
        if (newline(ch)) {
            multiline = true;
            s->bol = true;
            s->prefix = true;
            s->leading = 0;
        }
        if (previous == REPL_STAR && ch == REPL_SLASH) {
            lexer->mark_end(lexer);
            if (!s->braces && (multiline || first)) {
                while (horizontal(lexer->lookahead))
                    advance(lexer);
                if (!lexer->eof(lexer) && !newline(lexer->lookahead))
                    return false;
            }
            lexer->result_symbol = COMMENT;
            return true;
        }
        previous = ch;
    }
    return false;
}

static bool monitor_token(Scanner *s, TSLexer *lexer) {
    bool content = false, quoted = false;
    unsigned escapes = 0;
    int32_t previous = s->previous_space && s->space_column == lexer->get_column(lexer) ? ' ' : 0;
    if (s->bol && !s->physical_open && s->leading < s->indent * REPL_INDENT_WIDTH && !newline(lexer->lookahead))
        return false;
    while (!lexer->eof(lexer)) {
        const int32_t ch = lexer->lookahead;
        lexer->mark_end(lexer);
        if (!quoted && s->physical_open && (ch == REPL_OPEN_BRACE || ch == REPL_CLOSE_BRACE))
            break;
        if (!quoted && ch == REPL_SLASH) {
            const bool allowed_line = lexer->get_column(lexer) == 0 || previous == ' ' || previous == '\n';
            const uint32_t column = lexer->get_column(lexer);
            advance(lexer);
            if (lexer->lookahead == REPL_STAR || (lexer->lookahead == REPL_SLASH && allowed_line)) {
                if (!content)
                    return comment_token(s, lexer, allowed_line, s->bol);
                s->previous_space = allowed_line;
                s->space_column = column;
                s->bol = false;
                lexer->result_symbol = MONITOR_TEXT;
                return true;
            }
            content = true;
            previous = ch;
            continue;
        }
        if (ch == REPL_QUOTE && escapes % 2 == 0)
            quoted = !quoted;
        escapes = ch == REPL_ESCAPE ? escapes + 1 : 0;
        advance(lexer);
        content = true;
        previous = ch;
        if (newline(ch)) {
            if (!quoted && !s->physical_open) {
                lexer->mark_end(lexer);
                uint32_t spaces = 0;
                while (lexer->lookahead == ' ') {
                    advance(lexer);
                    spaces++;
                }
                if (!lexer->eof(lexer) && !newline(lexer->lookahead) && lexer->lookahead != '\r' &&
                    spaces < s->indent * REPL_INDENT_WIDTH) {
                    s->bol = true;
                    s->prefix = true;
                    s->leading = 0;
                    s->opened = false;
                    lexer->result_symbol = MONITOR_TEXT;
                    return true;
                }
            }
        }
    }
    if (content) {
        lexer->mark_end(lexer);
        s->bol = false;
        lexer->result_symbol = MONITOR_TEXT;
    }
    return content;
}

static bool scan(Scanner *s, TSLexer *lexer, const bool *valid) {
    if (valid[ERROR_SENTINEL])
        return false;
    if (valid[STRING_CONTENT] || valid[STRING_END])
        return string_token(lexer, false);
    if (valid[MULTILINE_CONTENT] || valid[MULTILINE_END])
        return string_token(lexer, true);
    if (lexer->eof(lexer)) {
        if (s->indent && valid[CLOSE]) {
            s->indent--;
            lexer->result_symbol = CLOSE;
            return true;
        }
        return false;
    }
    if ((!valid[MONITOR_TEXT] || s->bol) && (horizontal(lexer->lookahead) || newline(lexer->lookahead))) {
        do {
            const int32_t ch = lexer->lookahead;
            if (newline(ch)) {
                s->bol = true;
                s->opened = false;
                s->prefix = true;
                s->leading = 0;
            } else if (s->bol && s->prefix) {
                if (ch == ' ')
                    s->leading++;
                else if (ch != '\r')
                    s->prefix = false;
            }
            s->previous_space = ch == ' ';
            advance(lexer);
        } while (horizontal(lexer->lookahead) || newline(lexer->lookahead));
        s->space_column = lexer->get_column(lexer);
        if (s->bol && !s->started && s->leading)
            return false;
        lexer->result_symbol = SPACE;
        return valid[SPACE];
    }
    if (valid[MONITOR_TEXT] && (!s->bol || s->physical_open || s->leading >= s->indent * REPL_INDENT_WIDTH) &&
        (!s->physical_open || (lexer->lookahead != REPL_OPEN_BRACE && lexer->lookahead != REPL_CLOSE_BRACE)))
        return monitor_token(s, lexer);
    if (lexer->lookahead == REPL_SLASH) {
        const bool allowed_line =
            lexer->get_column(lexer) == 0 || (s->previous_space && s->space_column == lexer->get_column(lexer));
        const bool first = s->bol;
        advance(lexer);
        return comment_token(s, lexer, allowed_line, first) && valid[COMMENT];
    }
    if (s->bol && !s->braces) {
        if (s->leading % REPL_INDENT_WIDTH)
            return false;
        const uint32_t level = s->leading / REPL_INDENT_WIDTH;
        lexer->mark_end(lexer);
        if (level > s->indent && valid[OPEN]) {
            s->indent++;
            s->opened = true;
            s->physical_open = false;
            lexer->result_symbol = OPEN;
            return true;
        }
        if (level < s->indent && valid[CLOSE]) {
            s->indent--;
            s->opened = false;
            lexer->result_symbol = CLOSE;
            return true;
        }
        if (level != s->indent)
            return false;
        s->bol = false;
        if (s->started && !s->opened && valid[SEPARATOR]) {
            lexer->result_symbol = SEPARATOR;
            return true;
        }
        s->started = true;
        if (valid[LINE_START]) {
            lexer->result_symbol = LINE_START;
            return true;
        }
    }
    s->bol = false;
    if (lexer->lookahead == REPL_OPEN_BRACE && valid[OPEN]) {
        advance(lexer);
        s->braces++;
        s->physical_open = true;
        lexer->result_symbol = OPEN;
        return true;
    }
    if (lexer->lookahead == REPL_CLOSE_BRACE && valid[CLOSE] && s->braces) {
        advance(lexer);
        s->braces--;
        lexer->result_symbol = CLOSE;
        return true;
    }
    if (lexer->lookahead == REPL_SEPARATOR && valid[SEPARATOR]) {
        advance(lexer);
        lexer->result_symbol = SEPARATOR;
        return true;
    }
    return false;
}

bool tree_sitter_repl_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
    Scanner candidate = *(Scanner *)payload;
    if (!scan(&candidate, lexer, valid_symbols))
        return false;
    *(Scanner *)payload = candidate;
    return true;
}

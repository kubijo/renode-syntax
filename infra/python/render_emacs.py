"""Render Emacs lexical facts from the shared Renode extraction."""

import msgspec
from regex_source import RegexParser
from render_repl import ReplLexicon
from renode_model import RenodeData, SourceError


def products(data: RenodeData, platform: ReplLexicon) -> dict[str, bytes]:
    def strings(values: tuple[str, ...]) -> str:
        return '\n'.join('    ' + msgspec.json.encode(value).decode() for value in values)

    comment = next(rule for rule in data.tokenizer if rule.kind == 'CommentToken')
    tree = RegexParser(comment.dotnet).parse()
    if tree.kind != 'sequence' or not tree.children or tree.children[0].kind != 'literal':
        raise SourceError('Emacs requires a literal monitor comment prefix')
    source = (
        ';;; renode-ts-data.el --- Generated Renode facts -*- lexical-binding: t; -*-\n\n'
        ';; Generated from generated/renode.json; source provenance is recorded there.\n'
        ';; SPDX-License-Identifier: MIT\n\n'
        "(defconst renode-ts--commands\n  '(\n"
        + strings(tuple(command.name for command in data.commands))
        + "))\n\n(defconst renode-ts--keywords\n  '(\n"
        + strings(
            tuple(
                keyword.name
                for keyword in data.keywords
                if keyword.symbol
                in (
                    'UsingKeyword',
                    'NewKeyword',
                    'AsKeyword',
                    'LocalKeyword',
                )
            )
        )
        + '))\n\n'
        + '(defconst renode-ts--repl-comment '
        + msgspec.json.encode(platform.line_comment.value).decode()
        + ')\n'
        + '(defconst renode-ts--resc-comment '
        + msgspec.json.encode(tree.children[0].value).decode()
        + ')\n'
        + "\n(provide 'renode-ts-data)\n;;; renode-ts-data.el ends here\n"
    )
    return {'integrations/emacs/renode-ts-data.el': source.encode()}

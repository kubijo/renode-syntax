# Renode syntax

Syntax support for Renode platform descriptions (`.repl`) and monitor scripts (`.resc`). The repository provides Sublime
grammars, Tree-sitter parsers, a Zed extension and native Emacs modes. The grammars derive Renode keywords, commands and
lexer rules from pinned upstream sources.

## Use in an editor

- **Sublime Text and Sublime Merge:** the [Sublime grammars](integrations/sublime/) cover both file types. Install this
  repository under Sublime's `Packages/`. The [review guide](docs/sublime.md) covers embedded monitor and Python scopes
  in Sublime Merge.
- **bat:** install this repository under bat's syntaxes directory and run `bat cache --build`. Run the cache build again
  from this repository's Nix shell when using bat there: the shell keeps its separate cache under `.tmp/cache/bat/`.
- **Zed:** install the [development extension](docs/zed.md) from a checkout. It supports both languages, including
  embedded monitor and Python syntax. Registry publication is still a separate decision.
- **Emacs:** [install the modes from Git](integrations/emacs/readme.md). They require Emacs 30.1+ with native
  Tree-sitter.

The shared Tree-sitter grammars live in [tree-sitter/repl](tree-sitter/repl/) and [tree-sitter/resc](tree-sitter/resc/).

## Develop

Enter the locked Nix shell with `nix develop` or allow this repository's direnv configuration. Run `just` to discover
the maintainer commands and `just dev` for quality checks. The [brief](docs/brief.md) records the requirements and
derivation decisions.

Licensed under [MIT](LICENSE); see [NOTICE](NOTICE) for upstream attribution.

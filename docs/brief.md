# Renode syntax: requirements and decisions

This repository provides syntax support for Renode platform descriptions (`.repl`) and monitor scripts (`.resc`) in
Sublime Text/Merge, bat, Zed and Emacs. Mechanical facts come from pinned Renode sources; tests and a weekly upstream
sync guard the grammars. [Agent instructions](../.ai/instructions.md) own the workflow rules.

## Source of truth

- The platform grammar is `renode/renode` `src/Renode/PlatformDescription/Syntax/Grammar.cs`. Its `MakeKeyword` calls
  define keywords. `PreLexer.cs` in the same directory defines strings, comments and indentation rewriting. In
  particular, `//` starts a comment only at line start or after a space, preserving URLs; `/* */` spans lines; double
  quoted strings stay on one line; triple single quoted strings may span lines. Comment detection skips strings.
- The monitor lexer is `renode/renode-infrastructure` `src/Emulator/Extensions/UserInterface/Tokenizer/Tokenizer.cs`.
  Its regex token order matters: the first match at the current position wins. `#` and `:` start comments only at token
  boundaries after literals have had their chance.
- Monitor commands come from `UserInterface/Commands/*Command.cs`, registrations in `UserInterface/Monitor.cs`, and
  `renode/renode` `scripts/monitor.py`. Short aliases are intentionally unhighlighted because they collide with
  peripheral names. Script-local `mc_*` functions are not general commands.
- The original Sublime grammars and syntect runner came from `kubijo/sublime-merge-plugins` at `8e2b145`. Preserve their
  scopes and behavior where possible. Sublime Merge itself has not been verified; its engine may handle cross-syntax
  includes or indentation backreferences differently from syntect.
- `kubijo/xiaomi-fans` `tools/renode/` supplies real `.repl` and `.resc` corpus examples.

The repository uses MIT. Keep Renode's applicable copyright and MIT notices in [NOTICE](../NOTICE). The upstream
[license](https://github.com/renode/renode/blob/master/LICENSE) and source headers govern material extracted at the
tracked pins.

## Layout and consumers

- `integrations/sublime/` holds the rendered grammars and Sublime syntax assertions. The whole repository is installed
  under Sublime's `Packages/` or bat's syntaxes directory, so Sublime package files live only there.
- `tree-sitter/resc/` and `tree-sitter/repl/` hold the maintained grammars and committed generated parser sources. Zed
  requires Tree-sitter rather than Sublime syntax files.
- `integrations/zed/` holds one extension for both languages; `integrations/emacs/` holds both Emacs modes.
- `generated/` holds Renode facts shared by consumers. `infra/` holds automation and movable configuration. Disposable
  inputs, caches, builds and evidence belong under `.tmp/`.

Root configuration is limited to files whose tools discover them there. `kubijo/sublime-merge-plugins` will replace its
Renode package and runner with a submodule of this repository; its commits belong to that repository's owner.

## Derivation

The tracked pins in `infra/renode-pins.json` select `renode` and `renode-infrastructure` revisions. The generator reads
their sources into `generated/renode.json` and `generated/repl.json`, recording provenance, command registration forms,
keywords and lexer rules in source order. It uses Tree-sitter C# and Python's `ast`; Fissix normalizes IronPython 2
print statements before parsing `monitor.py`. Unknown registration forms, nonliteral names and unsupported regexes fail
the run. Source text is never scraped with regexes, and scripts are not executed.

.NET regexes are translated separately for Sublime's Oniguruma and Tree-sitter's Rust regex subset. Unsupported flags,
lookahead or lazy delimiters must be rewritten explicitly or rejected; JavaScript probes check an additional consumer.
Sublime grammars are rendered from templates because Sublime cannot import the generated data. Rendered files and parser
`src/` are committed, and the gate rejects stale output. Grammar structure, queries and the indentation scanner remain
maintained source.

Upstream checkouts are disposable inputs, not submodules. Prepare them at the tracked pins through `just source`; then
the gate runs offline and rejects modified inputs. Corpus preparation reads canonical Git blobs at those pins. The
Sublime corpus gate appends unclosed source sentinels and checks for leaked monitor or embedded language scopes. It does
not validate Renode semantics.

A general Sprache-to-Tree-sitter transpiler is outside scope: Sprache predicates and backtracking, custom combinators
and the imperative prelexer do not map directly to a Tree-sitter grammar.

## Grammar and editor behavior

- Sublime keeps the migrated scopes and assertions, including monitor bodies inside platform `init`, `reset` and
  `preinit`, plus embedded Python.
- Tree-sitter `resc` follows the monitor tokenizer and parses statements, macros, backtick execution and embedded
  `python """` blocks.
- Tree-sitter `repl` follows the platform grammar. Its external scanner implements indentation and comment rules from
  `PreLexer.cs`. Monitor bodies and `script: '''…'''` embed `resc` and Python respectively. Platform comments are
  excluded from monitor injection ranges; the corpus gate also parses those ranges with `resc`.
- Zed packages both grammars. The development extension is reviewed before publication; registry submission is a
  separate decision. The [review guide](zed.md) covers the development extension.
- Emacs provides native Tree-sitter modes for both languages on Emacs 30.1+ with grammar ABI 15. Embedded parsers have
  independent ranges and preserve platform comment exclusions. Installed Python grammar support adds Python
  highlighting; automatic indentation is deferred. Install directly from Git with `package-vc-install`; see
  [installation](../integrations/emacs/readme.md) and [review](emacs.md).

## Gates and upstream sync

The gate checks formatting and lint, Sublime assertions and scope sentinels, Tree-sitter grammar and pinned Renode
corpus parses, native Emacs behavior, and generated output freshness. Tree-sitter corpus parses must have zero `ERROR`
or `MISSING` nodes; Sublime sentinels must not leak. A grammar or generator fix needs a test proven to fail without the
fix. Use `just` and its modules for available commands.

Weekly automation proposes new pins from Renode `HEAD` and the infrastructure gitlink in that commit, regenerates and
opens a PR after all gates pass. Changes to `Grammar.cs` or `PreLexer.cs` require structural review; extraction or gate
failures produce an issue instead of an update PR. The workflow owns `automation/renode-sync` without force pushing and
identifies its PRs and issues through ownership markers. Manual runs default to dry run; scheduled runs publish. Local
replay under `.tmp/sync/` exercises a checked older-pin fixture. Hosted caching and publication still require a real
workflow run to verify; GitHub Actions must be allowed to create PRs.

The Nix flake pins `kubijo/nix-tools` and owns commands, dependencies, formatting and lint. `just` exposes thin
maintainer entry points from the active shell; direnv loads the locked shell. Python 3.15 tooling uses uv and uv2nix,
with a separate writable uv environment under `.tmp/`. Structured input uses msgspec, CLIs use Tyro, and terminal output
uses Rich. Implementation and exact tool versions live in the lock files and `infra/`.

## Remaining decisions

- Migrate `kubijo/sublime-merge-plugins` to a submodule in that repository, with its owner's commits.
- Decide whether to submit the Zed extension to the registry after reviewing a pinned release.

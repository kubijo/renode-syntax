# Renode syntax: requirements and decisions

Syntax support for Renode platform descriptions (`.repl`) and monitor scripts (`.resc`) in Sublime Text/Merge, bat, Zed
and Emacs. Mechanical facts come from Renode's sources; tests and a weekly upstream sync guard the grammars.
[Agent workflow](../.ai/instructions.md).

## Established facts (do not re-research; verify only where marked)

### Authoritative Renode sources

- Platform grammar: `renode/renode` `src/Renode/PlatformDescription/Syntax/Grammar.cs` (Sprache parser combinators).
  Keywords come from its `MakeKeyword(...)` calls:
  `using new as preinit init reset local true True false False none empty`; identifiers may not be keywords.

- Platform comments, strings and indentation: `src/Renode/PlatformDescription/PreLexer.cs`. `//` starts a comment only
  at line start or after a space (keeps `@https://…` intact); `/* */` spans lines; `"…"` is single-line with `\"`/`\\`
  escapes; `'''…'''` spans lines with `\'''` escaped; comment detection skips string contents. Indent mode is rewritten
  to braces here.

- Monitor tokens: `renode/renode-infrastructure` `src/Emulator/Extensions/UserInterface/Tokenizer/Tokenizer.cs`, an
  ordered `AddToken(new Regex(...), …)` list; first match at the current position wins. `#` and `:` start comments only
  at token start, after literals have had their chance (literals may contain `:`).

- Monitor commands, three registration forms:

  - `UserInterface/Commands/*Command.cs`: `base(monitor, "name", …)`; two use constants (`AutoSaveCommand.Command`,
    `NetworkLoggerCommand.FullCommand`);
  - `UserInterface/Monitor.cs`: `Commands.Add(new SetCommand(this, "set", …))` and similar
    (`set macro alias execute runMacro`);
  - `renode/renode` `scripts/monitor.py`: `def mc_<name>` functions (`echo if sleep print str_contains …`).

  Short aliases (`s`, `p`, `q`, `i`, …) are deliberately not highlighted; they collide with peripheral names. `mc_*`
  functions in test or board scripts are script-local, not general commands.

- Change rate in 2026: `Grammar.cs` 6 commits (`none` entries, dict constructor params, bool literals, `using`
  semicolons, empty statements), `Tokenizer.cs` 4 (exponents, `TimeIntervalToken`, colons in literals, bools), new
  commands (`printenv`, `print`/`pyprint`, `str_contains`). `PreLexer.cs` is stable since 2025-05.

- Licensing: Renode's root [LICENSE](https://github.com/renode/renode/blob/master/LICENSE) and the `Grammar.cs`,
  `Tokenizer.cs`, and `Monitor.cs` headers declare MIT. The latter two also credit Realtime Embedded. Retain the
  applicable copyright notices and full MIT text in `NOTICE`; verify additional extraction sources at the pins.

### Sublime compatibility

The Sublime grammars and syntect runner originated in `kubijo/sublime-merge-plugins` at `8e2b145`:

- `Renode/RenodePlatform.sublime-syntax` (`source.renode.repl`) and `Renode/RenodeScript.sublime-syntax`
  (`source.renode.resc`). Platform `init:`/`reset:`/`preinit:` bodies include `scope:source.renode.resc#statements`; the
  indent-mode block pops on a backreference to the keyword's indentation. `python """…"""` and `script: '''…'''` embed
  `source.python`.
- `syntax_test_renode.{repl,resc}` uses Sublime-format assertions. The Rust runner resolves the header grammar by file
  name, accepts indented assertion lines and builds under `.tmp/` to keep output out of Sublime's package scan.
- **Unverified**: loading in Sublime Merge itself. Its engine may differ from syntect on cross-syntax `scope:…#context`
  includes and backreferences in `pop`.

### Ecosystem

- Zed highlights only through Tree-sitter grammars packaged in extensions; it does not load TextMate or Sublime
  grammars.
- No usable prior art: `achmutov/tree-sitter-resc` is a 4-commit `.resc`-only draft without committed `src/`, LICENSE
  file or tests. Antmicro's `renode-vscode-extension` contributes only a debugger. Zed's registry has no Renode
  extension.
- Zed's `extension.toml` grammar entries take `repository`, `rev` and optional `path`; its
  [builder](https://github.com/zed-industries/zed/blob/main/crates/extension/src/extension_builder.rs) compiles
  generated `src/` without running `tree-sitter generate`. Registry submission accepts an extension in a
  [subdirectory](https://zed.dev/docs/extensions/publishing/publishing-guide) and requires a
  [license file](https://zed.dev/docs/extensions/publishing/license-requirements) there; a symlink is accepted.
- A full Sprache-to-Tree-sitter transpiler is rejected. `.Where` predicates, `Or`/`XOr` backtracking, the custom
  `XOptional` and `Positioned` do not map to a GLR grammar, and the prelexer is imperative code.

### Consumers

- `kubijo/sublime-merge-plugins` will include this repository as a submodule, replacing its `Renode/` and
  `tools/syntax-test/`. Its clones live in Sublime Merge's `Packages/` and in bat's syntaxes directory, so this
  repository is cloned there whole.
- `kubijo/xiaomi-fans` `tools/renode/` is a real-world `.repl`/`.resc` corpus.

## Requirements and decisions

### License

This repository uses MIT. Renode-derived material retains its applicable upstream copyright and MIT notices in `NOTICE`.

### Layout

| Path                    | Owns                                                                           |
| ----------------------- | ------------------------------------------------------------------------------ |
| `integrations/sublime/` | Sublime grammars and `syntax_test_*` assertions                                |
| `tree-sitter/repl/`     | Platform grammar: `grammar.js`, external scanner, committed generated `src/`   |
| `tree-sitter/resc/`     | Monitor grammar: `grammar.js`, committed generated `src/`                      |
| `integrations/zed/`     | Zed extension: `extension.toml`, `languages/`, queries                         |
| `integrations/emacs/`   | Emacs modes and generated lexical facts                                        |
| `generated/`            | Derived Renode data consumed by both grammar families                          |
| `infra/`                | Tool configs that can move, the generator, the syntect runner, CI scripts, Nix |
| `.tmp/`                 | Every temporary artifact: Renode checkouts, build targets, caches, dumps       |
| `docs/`, `.ai/`         | This brief, decisions, agent instructions                                      |

Root keeps only what tools discover natively: `.envrc`, `flake.nix`, `flake.lock`, `justfile`, `pyproject.toml`,
`uv.lock`, `tree-sitter.json`, `LICENSE`, notices, `.gitignore`, agent entry symlinks. Because whole-repository clones
land in Sublime and bat, no `.sublime-syntax`, `.tmPreferences` or `.sublime-settings` may exist outside
`integrations/sublime/`, and build output is never committed.

### Derivation

- A generator reads Renode at pinned commits of `renode` and `renode-infrastructure`, recorded in a tracked pin file and
  fetched into `.tmp/`. It emits `generated/renode.json`: commands (with source file and registration form), keywords,
  and tokenizer rules in upstream order.
- Extraction uses real parsers: Tree-sitter C# for the C# sources and Python's `ast` for `monitor.py`. An unrecognised
  registration form, a non-literal name or an untranslatable regex fails the run. Regex scraping of source text and
  silent fallbacks are not acceptable. The default script uses IronPython 2 syntax; Fissix normalizes its print
  statements before AST extraction, without executing the script.
- .NET regexes are translated per consumer: Oniguruma for Sublime and the
  [Rust-regex subset](https://tree-sitter.github.io/tree-sitter/creating-parsers/2-the-grammar-dsl.html) for
  Tree-sitter. Inline flags, lookahead and lazy delimiter matching must be explicitly rewritten or rejected. JavaScript
  translations are also compiled and probed as an independent consumer check.
- Sublime cannot import data, so its grammars are rendered from templates plus the generated data. Rendered files are
  committed (Sublime and bat load them directly), and a check fails when they are stale.
- Structure (contexts, Tree-sitter rules, the indentation scanner, queries) is hand-written once.

Upstream checkouts are disposable inputs, not submodules. Fetch the tracked pins before generation or a first local
quality-gate run; checks then work offline and reject modified inputs. Use `just source` to discover that workflow.
Corpus preparation reads canonical Git blobs at both pins and records their identities under `.tmp/corpus/`. The Sublime
gate appends ordinary source sentinels without closing delimiters and checks their scopes, including that monitor and
embedded-language contexts have ended. It detects context leaks rather than validating Renode semantics.

### Grammars and editor support

- Sublime: keep current behaviour and scopes; existing assertions must keep passing after migration.
- Tree-sitter `resc`: tokens follow `Tokenizer.cs`; statements, `macro` bodies, backtick execution, `python """` with a
  Python injection.
- Tree-sitter `repl`: follows `Grammar.cs`; an external scanner ports `PreLexer.cs` indentation and comment rules.
  Inject `resc` into `init`/`reset`/`preinit` bodies and Python into `script: '''…'''`.
- Platform lexer facts and scanner constants come from `generated/repl.json`. The maintained scanner lives beside
  `grammar.js`; parser generation copies it and emits its configuration header under `src/`. Platform comments are
  excluded from monitor injection ranges, and the corpus gate parses those same ranges with `resc`.
- Zed: one extension covering both languages, installed as a dev extension first. Registry publication is a later,
  separate decision.
- Emacs: native Tree-sitter modes for both languages, requiring Emacs 30.1+ and grammar ABI 15. Embedded parsers are
  independent and preserve platform comment exclusions. Derive lexical facts from the shared extraction; reuse the
  installed Python mode's highlighting when its optional grammar is available. Use Emacs's standard grammar installer;
  automatic indentation is deferred. Nix defines native preparation, elisp-autofmt, package-lint, strict byte
  compilation and ERT. See [installation and review](emacs.md).

### Quality gates

- Sublime syntax tests through the syntect runner.
- Tree-sitter corpus tests per grammar.
- Native Emacs tests for highlighting, independent embedded ranges, edits, comments and navigation.
- Renode corpus at the pinned commits: zero `ERROR`/`MISSING` nodes for Tree-sitter, zero sentinel leaks for Sublime.
- A fix lands with a test that fails without it.
- nix-tools formatting and lint over every tracked file.

### Automation

- Weekly GitHub workflow: move pins to Renode `HEAD`, regenerate, render, run all gates, open a PR when anything
  changed.
- A change to `Grammar.cs` or `PreLexer.cs` between pins opens an issue for structural review instead of passing
  silently. Gate failures on new upstream content open an issue.
- Workflow YAML stays declarative; orchestration lives in checked scripts under `infra/`.

The weekly runner installs Nix and uses Determinate's Magic Nix Cache with GitHub caching enabled and FlakeHub disabled,
following `garmin-toolbox`. Local sync rehearsals run in isolated worktrees under `.tmp/sync/` and save the proposed
patch, PR or issue text and validation logs under `.tmp/sync/artifacts/`. Discover entry points with `just sync`.

Infrastructure advances to the gitlink recorded by the selected Renode commit. Structural changes block regeneration and
publication of the update PR; failed extraction or validation also produces a review issue. Publication updates the
reserved `automation/renode-sync` branch without force pushing and identifies its PR and issues through ownership
markers. A manual workflow run defaults to a dry run; the weekly schedule publishes. GitHub Actions must be allowed to
create pull requests in the repository settings. A local replay exercises the checked older-pin fixture without GitHub
writes; actual hosted-runner caching and publication require a workflow run to verify.

### Tooling

- Nix flake with `kubijo/nix-tools` pinned to a release tag (`v0.10.0` in sibling repositories), following its packaging
  inputs. The root flake hands off to `infra/nix/flake.nix`. nix-tools supplies `repofmt`, `repochk` and checks; extra
  formatters for Rust, JavaScript and maintained C sources are declared there. Parser `src/` products retain the
  generator's output format.
- Nix owns command definitions and dependencies. `just` exposes maintainer entry points through thin modules that import
  `infra/just/prelude.just`. Module justfiles live in their context directories where applicable; application modules
  are nested under `just integrations`. Commands assume the Nix shell is already active.
- direnv loads the full locked development shell, with its layout and caches under `.tmp/`.
- Python support tooling lives under `infra/python/`: Python 3.15, uv-managed dependencies, and a uv2nix environment
  built from the root `pyproject.toml` and `uv.lock`. Editors discover the same immutable environment through
  `.tmp/venv/nix`; uv syncs a separate writable environment at `.tmp/venv/tooling`. Rich owns terminal presentation;
  Tyro owns CLIs and msgspec owns structured input.
- Bash owns environment exports and direnv integration. Python owns structured diagnostics and executes the quality-gate
  plans declared by Nix, including saved logs and Rich status output.

## Plan (phases and gates)

0. Bootstrap: flake, prelude and modules, `.gitignore`, LICENSE and Renode notice. Copy the Sublime grammars, tests and
   runner from `sublime-merge-plugins` without behaviour changes. Gate: format/lint clean, 540 assertions pass.
1. Generator, pin file and `generated/renode.json`; Sublime templates render from it. Gate: rendered grammars match the
   migrated ones except reviewed differences; assertions pass.
2. Renode corpus gate for Sublime under `.tmp/`. Gate: zero leaks at the pins.
3. Tree-sitter `resc`, Zed extension with `resc`, corpus parse. Gate: zero parse errors; user reviews it in Zed.
4. Weekly workflow and structural-change issues. Gate: a dry run against an older pin produces the expected PR content.
5. Tree-sitter `repl` with the indentation scanner; `repl` in Zed. Gate: zero parse errors on the corpus.
6. Group application products under `integrations/`; preserve shared grammars and generated data at the root. Gate:
   product contents unchanged and all quality checks pass.
7. Emacs modes with native grammar preparation and embedded languages. Gate: byte compilation and native ERT pass,
   followed by user review in Emacs.
8. `sublime-merge-plugins` switches to this repository as a submodule. Its commits are the user's.

## Open choices

- Repository name (`renode-syntax`) and visibility.
- Zed registry publication.

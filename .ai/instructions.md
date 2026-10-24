# Agent instructions

Read `docs/brief.md` in full before editing. The brief owns requirements and major decisions; workflow rules live here,
implementation detail in code. Ask about unresolved or conflicting requirements. Work one phase at a time; at its gate
report changes and check results, propose the next concrete step, then stop.

# Layout

- Keep agent entry points as relative symlinks to this file. Shared instructions and repository skills live under
  `.ai/`.
- Product directories (`sublime/`, `tree-sitter/`, `zed/`, `generated/`) hold only product files. The whole repository
  is cloned into Sublime's `Packages/` and bat's syntaxes directory: never put `.sublime-syntax`, `.tmPreferences` or
  `.sublime-settings` files outside `sublime/`, and never commit build output.
- Keep reusable automation tracked under `infra/`. Preserve native CLI and IDE configuration discovery; put explicitly
  loaded configuration under `infra/` and pass its paths explicitly. Keep a config at the root only when its tool cannot
  be pointed elsewhere.
- Every temporary, cache, checkout, build target and evidence file lives under a named `.tmp/` directory, set through
  supported tool settings. Never write to `/tmp` or the user's caches.

# Derivation

- Derive mechanical facts from Renode's sources through the generator; never hand-copy commands, keywords or token
  rules. Generated data records the upstream file each fact came from.
- Parse sources with real parsers. Fail loudly on any form the generator does not recognise; no silent fallbacks.
- Never hand-edit generated or rendered files: `generated/`, rendered `.sublime-syntax` output and Tree-sitter `src/`.
  Change the generator, template or `grammar.js` and regenerate.
- A grammar or generator fix ships with a test that fails without it; prove that by reverting the fix once.

# Commands and scripts

- Nix defines commands and dependencies; `just` lists maintainer entry points as one-line calls to those commands.
  Assume the Nix shell is active. The root justfile routes modules; every module imports `infra/just/prelude.just`. Put
  procedures in checked-in support tooling.
- Never run heredocs, inline interpreter scripts or piped source, including for diagnostics.
- Run prepared validation targets bare and inspect their saved output afterwards.
- Ask before long-running, network-heavy or destructive commands. Never start watchers or servers unasked.

# Code

- Nix: inherit used `builtins` attributes at the top of the scope. Never use `path:.` flake references.
- Python: fully annotated; validate every Python file with nix-tools' Basedpyright in strict mode and format it with
  nix-tools' Ruff. Use tyro for CLIs and Rich for terminal styling and tabular layouts.
- All JSON, YAML, and TOML parsing and serialization in Python must use msgspec. Decode into explicit types and validate
  external data at the boundary.
- Manage Python dependencies with uv and uv2nix. Keep uv's writable project environment separate from Nix store
  environments.
- Rust: clippy pedantic clean.
- Keep CI YAML declarative; orchestration and branching belong in checked scripts under `infra/`.

# Reporting and git

- Suggest the next concrete step when reporting a completed milestone or commit.
- Flag anything unverified rather than assuming, especially behaviour in Sublime Merge and Zed, which the checks here
  only approximate.
- Stay on the current branch. Never stage, unstage, commit or push without explicit approval. At a commit boundary
  propose files, a message (imperative subject, a few short bullets) and the reason, then wait.

# Documentation

- One home per fact: the brief owns decisions and comments explain why. Use `just`, `just dev`, or the relevant module
  for command discovery; never duplicate recipe catalogs or generated help in documentation.
- Drop completed checklist items, chronology and per-run results from committed docs; report run results in chat.
- Markdown tables are ASCII and at most 119 source columns, including padding; check after formatting.

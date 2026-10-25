{
  pkgs,
  project,
  pythonTools,
  nodejs,
  wasiSdk,
  emacs,
  emacsBatch,
  pythonGrammar,
}:
let
  inherit (builtins) toJSON;
  inherit (pkgs) lib;
  python = "${pythonTools}/bin/python";
  uv = lib.getExe pkgs.uv;
  cargo = lib.getExe pkgs.cargo;
  nix = lib.getExe pkgs.nix;
  step = name: argv: { inherit name argv; };
  format = step "format" [ project.apps.format.program ];
  lint = [
    (step "lint" [ project.apps.lint.program ])
    emacsCompile
    (step "clippy" [
      cargo
      "clippy"
      "--locked"
      "--manifest-path"
      "infra/syntax-test/Cargo.toml"
      "--all-targets"
      "--"
      "-D"
      "warnings"
      "-W"
      "clippy::pedantic"
    ])
  ];
  syntax = step "syntax" [
    cargo
    "run"
    "--release"
    "--locked"
    "--quiet"
    "--manifest-path"
    "infra/syntax-test/Cargo.toml"
    "--"
    "integrations/sublime"
  ];
  runnerTests = step "runner-tests" [
    cargo
    "test"
    "--locked"
    "--manifest-path"
    "infra/syntax-test/Cargo.toml"
  ];
  corpusPrepare = step "corpus-prepare" [
    python
    "infra/python/corpus.py"
    "prepare"
  ];
  corpus = [
    corpusPrepare
    (step "corpus" [
      cargo
      "run"
      "--release"
      "--locked"
      "--quiet"
      "--manifest-path"
      "infra/syntax-test/Cargo.toml"
      "--"
      "--corpus"
      "integrations/sublime"
      ".tmp/corpus/files0"
    ])
  ];
  toolingTests = step "tooling-tests" [
    python
    "-m"
    "unittest"
    "discover"
    "--start-directory"
    "infra/python"
    "--pattern"
    "test_*.py"
  ];
  lockCheck = step "python-lock" [
    uv
    "lock"
    "--check"
    "--offline"
  ];
  source =
    action:
    step "source-${action}" [
      python
      "infra/python/generate.py"
      action
    ];
  regexCheck = step "regex" [
    (lib.getExe nodejs)
    "infra/javascript/check-regex.mjs"
    "generated/renode.json"
  ];
  parser =
    action:
    step "parser-${action}" [
      python
      "infra/python/treesitter.py"
      action
    ];
  zed = step "zed-prepare" [
    python
    "infra/python/zed_extension.py"
    "--compiler"
    "${wasiSdk}/bin/clang"
  ];
  wasmCheck = step "zed-wasm" [
    (lib.getExe nodejs)
    "infra/javascript/check-wasm.mjs"
    ".tmp/zed/extension/grammars"
  ];
  emacsPrepare = step "emacs-prepare" [
    python
    "infra/python/emacs_support.py"
    "--python-grammar"
    "${pythonGrammar}/parser"
    "--suffix"
    pkgs.stdenv.hostPlatform.extensions.sharedLibrary
  ];
  emacsCompile = step "emacs-compile" [
    (lib.getExe emacsBatch)
    "--load"
    "infra/emacs/compile.el"
  ];
  emacsTest = step "emacs-test" [
    (lib.getExe emacsBatch)
    "--load"
    ".tmp/emacs/setup.el"
    "--load"
    "infra/emacs/test.el"
    "--funcall"
    "ert-run-tests-batch-and-exit"
  ];
  plans = {
    format = [ (format // { forward_arguments = true; }) ];
    inherit lint;
    check = [
      (format // { argv = format.argv ++ [ "--ci" ]; })
      lockCheck
    ]
    ++ lint
    ++ [
      toolingTests
      runnerTests
      (source "check")
      regexCheck
      syntax
    ]
    ++ corpus
    ++ [
      (parser "check")
      (parser "test")
      (parser "corpus")
      zed
      wasmCheck
      emacsPrepare
      emacsTest
    ];
    emacs-prepare = [ emacsPrepare ];
    test-emacs = [
      corpusPrepare
      emacsCompile
      emacsPrepare
      emacsTest
    ];
    source-parser = [ ((parser "generate") // { forward_arguments = true; }) ];
    source-parser-tests = [ ((parser "update-tests") // { forward_arguments = true; }) ];
    test-parser = [ ((parser "test") // { forward_arguments = true; }) ];
    test-parser-corpus = [ ((parser "corpus") // { forward_arguments = true; }) ];
    zed-prepare = [
      zed
      wasmCheck
    ];
    zed-review = [
      zed
      wasmCheck
      (step "zed-open" [
        "zed"
        "--user-data-dir"
        ".tmp/zed/data"
        "."
        ".tmp/zed/review.repl"
      ])
    ];
    test-syntax = [ syntax ];
    test-tooling = [ toolingTests ];
    test-runner = [ runnerTests ];
    test-corpus = corpus;
    source-fetch = [ (source "fetch") ];
    source-generate = [ (source "generate") ];
    source-check = [
      (source "check")
      regexCheck
      (parser "check")
    ];
    python-lock = [
      (step "python-lock" [
        uv
        "lock"
      ])
    ];
    python-sync = [
      (step "python-sync" [
        uv
        "sync"
        "--locked"
      ])
    ];
    flake-lock = [
      (step "nix-lock" [
        nix
        "flake"
        "lock"
      ])
    ];
    flake-check = [
      (step "flake" [
        nix
        "flake"
        "check"
        "--no-update-lock-file"
      ])
    ];
  };
  command =
    name: arguments:
    pkgs.writeShellApplication {
      name = "renode-${name}";
      text = ''
        exec ${python} "$RENODE_SYNTAX_ROOT/infra/python/manage.py" ${arguments} "$@"
      '';
    };
  fromPlans = lib.mapAttrs (
    name: steps:
    command name "run --plan ${
      pkgs.writeText "renode-${name}-plan.json" (toJSON {
        inherit steps;
      })
    }${lib.optionalString (lib.any (item: item.forward_arguments or false) steps) " --"}"
  );
  commands = fromPlans plans;
  sync = action: [
    (
      (step "sync-${action}" [
        python
        "infra/python/upstream_sync.py"
        action
        "--gate"
        (lib.getExe commands.check)
        "--python-environment"
        "${pythonTools}"
      ])
      // {
        forward_arguments = action == "dry-run";
      }
    )
  ];
in
commands
// fromPlans {
  sync-dry-run = sync "dry-run";
  sync-replay = sync "replay";
  sync-publish = sync "publish";
  sync-ci = sync "ci";
}
// {
  doctor = command "doctor" "doctor";
  emacs-review = pkgs.writeShellApplication {
    name = "renode-emacs-review";
    text = ''
      cd "$RENODE_SYNTAX_ROOT"
      ${lib.getExe commands.emacs-prepare}
      exec "''${1:-${lib.getExe emacs}}" \
        --load "$RENODE_SYNTAX_ROOT/.tmp/emacs/setup.el" \
        "$RENODE_SYNTAX_ROOT/.tmp/emacs/review.repl"
    '';
  };
}

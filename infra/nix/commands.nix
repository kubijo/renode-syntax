{
  pkgs,
  project,
  pythonTools,
  nodejs,
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
    "sublime"
  ];
  runnerTests = step "runner-tests" [
    cargo
    "test"
    "--locked"
    "--manifest-path"
    "infra/syntax-test/Cargo.toml"
  ];
  corpus = [
    (step "corpus-prepare" [
      python
      "infra/python/corpus.py"
      "prepare"
    ])
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
      "sublime"
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
    ++ corpus;
    test-syntax = [ syntax ];
    test-tooling = [ toolingTests ];
    test-runner = [ runnerTests ];
    test-corpus = corpus;
    source-fetch = [ (source "fetch") ];
    source-generate = [ (source "generate") ];
    source-check = [
      (source "check")
      regexCheck
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
in
lib.mapAttrs (
  name: steps:
  command name "run --plan ${
    pkgs.writeText "renode-${name}-plan.json" (toJSON {
      inherit steps;
    })
  }"
) plans
// {
  doctor = command "doctor" "doctor";
}

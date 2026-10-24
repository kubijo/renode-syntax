{
  pkgs,
  project,
  pythonTools,
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
      syntax
    ];
    test-syntax = [ syntax ];
    test-tooling = [ toolingTests ];
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

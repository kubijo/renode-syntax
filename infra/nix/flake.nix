{
  self,
  nixpkgs,
  nix-tools,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
  ...
}:
let
  inherit (nixpkgs) lib;
  forSystems = lib.genAttrs [
    "x86_64-linux"
    "aarch64-linux"
    "aarch64-darwin"
  ];
  tooling = forSystems (
    system:
    let
      pkgs = nixpkgs.legacyPackages.${system};
      toolPkgs = nix-tools.lib.toolPkgsFor system;
      pythonTools = import ./python-tools.nix {
        inherit
          pkgs
          pyproject-nix
          uv2nix
          pyproject-build-systems
          ;
      };
      nodejs = pkgs.nodejs_26;
      wasiCompiler = pkgs.pkgsCross.wasi32.stdenv.cc;
      wasiSdk = pkgs.writeShellScriptBin "clang" ''
        # Tree-sitter supplies scanner libc imports in its WASM runtime. The Nix
        # cross libc is static and cannot be linked into Zed's shared modules.
        exec ${wasiCompiler}/bin/${wasiCompiler.targetPrefix}cc \
          -fuse-ld=${pkgs.llvmPackages.lld}/bin/wasm-ld \
          -nostdlib -Wl,--no-entry -Wl,--allow-undefined "$@"
      '';
      basedpyright = toolPkgs.basedpyright.override {
        buildNpmPackage = toolPkgs.buildNpmPackage.override { inherit nodejs; };
      };
      prepareEnvironment = ''
        source ${./environment.sh}
        mkdir -p "$RENODE_SYNTAX_ROOT/.tmp/venv"
        ln -sfn ${pythonTools} "$RENODE_SYNTAX_ROOT/.tmp/venv/nix"
      '';
      project = nix-tools.lib.configure {
        inherit system nodejs;
        src = self;

        unexclude = [
          ".gitignore"
          "Cargo.toml"
        ];

        # The entry points are symlinks to the maintained instruction file.
        exclude = [
          "AGENTS.md"
          "CLAUDE.md"
        ];

        format = {
          walk = "filesystem";
          # Preserve the migrated grammars and assertion columns byte-for-byte.
          exclude = [
            # A linked worktree has a .git pointer file rather than a directory.
            ".git"
            "sublime/**"
            # These are reproduced by the parser generator, including its scanner copy.
            "tree-sitter/*/src/**"
          ];
          rust = {
            exe = lib.getExe pkgs.rustfmt;
            options = [
              "--edition"
              "2021"
            ];
          };
          javascript = true;
          extraFormatters.c = {
            # Formatting needs no compiler header wrapper or ambient PATH utilities.
            command = lib.getExe' pkgs.clang-tools "clang-format-unwrapped";
            options = [
              "-i"
              "--style=file:${../clang-format.yaml}"
            ];
            cacheInputs = [ ../clang-format.yaml ];
            includes = [
              "*.c"
              "*.h"
            ];
          };
          python.configFile = ../../pyproject.toml;
          shell.includes = [
            "*.sh"
            ".envrc"
          ];
          whitespace.includes = [
            ".gitignore"
            "LICENSE"
            "NOTICE"
            "*.in"
            "*.scm"
            "*.txt"
            "*.repl"
            "*.resc"
          ];
        };

        lint = {
          javascript = true;
          python.configFile = ../../pyproject.toml;
          basedpyright.projects.tooling = {
            configFile = "pyproject.toml";
            python = pythonTools;
            package = basedpyright;
            reporter = "rich";
          };
          shell.includes = [
            "*.sh"
            ".envrc"
          ];
          whitespace.includes = [
            ".gitignore"
            "LICENSE"
            "NOTICE"
            "*.in"
            "*.scm"
            "*.txt"
            "*.repl"
            "*.resc"
            "*.c"
            "*.h"
          ];
        };

        check.prepare = prepareEnvironment;
      };
      commands = import ./commands.nix {
        inherit
          pkgs
          project
          pythonTools
          nodejs
          wasiSdk
          ;
      };
    in
    {
      inherit (project) checks formatter;
      apps =
        project.apps
        // lib.mapAttrs (_: package: {
          type = "app";
          program = lib.getExe package;
        }) commands;
      packages = commands // {
        inherit (pkgs) nix-direnv;
        python-tools = pythonTools;
      };
      devShell = pkgs.mkShell {
        packages =
          project.packages
          ++ lib.attrValues commands
          ++ [
            basedpyright
            nodejs
            pkgs.bash
            pkgs.cargo
            pkgs.clippy
            pkgs.coreutils
            pkgs.direnv
            pkgs.git
            pkgs.nix
            # Match the Just parser used by nix-tools to format these modules.
            toolPkgs.just
            toolPkgs.ruff
            pkgs.pkg-config
            pkgs.tree-sitter
            pkgs.rustc
            pkgs.rustfmt
            pythonTools
            pkgs.uv
          ];
        WASI_SDK_PATH = "${wasiSdk}";
        UV_PYTHON = "${pythonTools}/bin/python";
        shellHook = prepareEnvironment;
      };
    }
  );
in
{
  apps = forSystems (system: tooling.${system}.apps);
  checks = forSystems (system: tooling.${system}.checks);
  formatter = forSystems (system: tooling.${system}.formatter);
  packages = forSystems (system: tooling.${system}.packages);
  devShells = forSystems (system: {
    default = tooling.${system}.devShell;
  });
}

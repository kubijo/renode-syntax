{
  pkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
let
  python = pkgs.python315;
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ../..; };
  pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
    pkgs.lib.composeManyExtensions [
      pyproject-build-systems.overlays.wheel
      (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
      (final: previous: {
        tree-sitter = previous.tree-sitter.overrideAttrs (old: {
          nativeBuildInputs =
            (old.nativeBuildInputs or [ ]) ++ final.resolveBuildSystem { setuptools = [ ]; };
        });
      })
    ]
  );
in
pythonSet.mkVirtualEnv "renode-python-tools" workspace.deps.default

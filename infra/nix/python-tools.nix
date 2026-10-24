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
    ]
  );
in
pythonSet.mkVirtualEnv "renode-python-tools" workspace.deps.default

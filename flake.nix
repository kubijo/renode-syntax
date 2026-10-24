{
  description = "Renode syntax support for Sublime Text, bat, and Zed";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    nix-tools.url = "github:kubijo/nix-tools/v0.10.0";
    # Share packaging revisions without overriding nix-tools' tool pin.
    pyproject-nix.follows = "nix-tools/pyproject-nix";
    uv2nix.follows = "nix-tools/uv2nix";
    pyproject-build-systems.follows = "nix-tools/pyproject-build-systems";
  };

  outputs = inputs: import ./infra/nix/flake.nix inputs;
}

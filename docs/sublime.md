# Reviewing Sublime Merge

Use the `integrations::sublime` Just module from the Nix shell. Its review entry point copies the working
`.sublime-syntax` files into an isolated profile under `.tmp/sublime-merge/` and opens this repository in Sublime Merge.
It reuses that profile on later runs and does not pass `--new-window` to the launcher.

In **Changes**, open `infra/fixtures/scope-boundaries.repl` and `infra/fixtures/review.resc`. They are new, non-ignored
files, so Merge shows their full contents before the review is committed. Check that `.repl` starts in Renode Platform;
`init` and `reset` bodies switch to Renode Script; embedded Python switches to Python; and subsequent entries return to
Renode Platform. In `.resc`, check commands, `#` comments, the URL path, macro body and embedded Python.

After the fixtures are committed, pass a fixture path to the review entry point to open its blame view with the same
isolated profile. The automated syntect runner checks scope assertions, but only an editor review can verify Sublime
Merge's rendering and package loading.

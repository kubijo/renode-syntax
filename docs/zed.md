# Reviewing the Zed extension

Prepare the dev extension from the active Nix shell using the `zed` Just module. It builds the working parser with the
locked WASI compiler and puts the extension, grammar checkout and WASM under `.tmp/zed/`. The preparation copies working
parser files into a disposable local clone so uncommitted changes can be reviewed without changing the parent Git index
or history. Run preparation again after changing the grammar or queries.

Use the `zed` module's review entry point to prepare the artifact and launch a separate instance of your installed Zed.
It preserves the shell's `WASI_SDK_PATH` and keeps editor state and SDK caches under `.tmp/zed/data`. Run **Install Dev
Extension** in Zed and select `.tmp/zed/extension`. Open monitor scripts from the pinned corpus under
`.tmp/corpus/input/` and check builtin commands, macro bodies, bracket matching, outlines and Python blocks.

The tracked extension manifest describes the development branch. The prepared manifest points to the local repository at
its exact current commit; its seeded working parser and prebuilt WASM include uncommitted changes. Publishing requires a
separate decision and a grammar revision containing the committed generated `src/` files.

Automated checks compile every query and test capture boundaries against the native parser. They do not verify Zed's
rendering, theme choices, injection integration or interactive editing behaviour. Those need the editor review at the
phase gate. Platform descriptions remain a later grammar phase.

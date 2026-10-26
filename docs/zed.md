# Reviewing the Zed extension

Use the `integrations::zed` Just module from the Nix shell to prepare or review the extension. Preparation builds both
parsers with the locked WASI compiler under `.tmp/zed/`, including uncommitted parser changes. Repeat it after grammar
or query edits.

The review instance preserves `WASI_SDK_PATH` and keeps editor state and SDK caches under `.tmp/zed/data`. Run **Install
Dev Extension** and select `.tmp/zed/extension`. Open `.tmp/zed/review.repl` to check indentation, explicit blocks,
monitor bodies, nested Python and the return to platform syntax. Use the pinned corpus under `.tmp/corpus/input/` for
broader review of commands, macros, brackets and outlines. Python highlighting needs Zed's Python language support.

The tracked manifest pins a grammar revision containing the generated `src/` files. The prepared manifest instead uses
the local repository at its current commit; review the tracked manifest from the exact release checkout before
submitting it to the registry.

Automated checks compile queries and test native parse and capture boundaries. Review rendering, injection integration
and interactive editing in Zed at the phase gate.

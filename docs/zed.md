# Reviewing the Zed extension

Use the `zed` Just module from the Nix shell to prepare the working extension or launch a review instance. Preparation
builds both parsers with the locked WASI compiler and keeps the extension, disposable grammar clones and WASM under
`.tmp/zed/`. Repeat it after changing grammars or queries; uncommitted parser changes are included.

The review instance preserves `WASI_SDK_PATH` and keeps editor state and SDK caches under `.tmp/zed/data`. Run **Install
Dev Extension** in Zed and select `.tmp/zed/extension`. Open monitor scripts from the pinned corpus under
`.tmp/corpus/input/` and check builtin commands, macro bodies, bracket matching, outlines and Python blocks. The
prepared `.tmp/zed/review.repl` fixture exercises indented and explicit platform blocks, monitor bodies, nested Python
and the return to platform syntax. Its Python content needs Zed's Python language support.

The tracked manifest uses the development branch; the prepared manifest uses the local repository at its current commit.
Publishing requires a separate decision and a grammar revision containing the generated `src/` files.

Automated checks compile queries and test native parse and capture boundaries. Review rendering, injection integration
and interactive editing in Zed at the phase gate.

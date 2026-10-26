# Reviewing the Emacs modes

See the [Emacs integration README](../integrations/emacs/readme.md) for requirements and installation from Git.

Use the `integrations::emacs` Just module to prepare or launch a review. Review opens the fixture with the setup
preloaded, using pinned terminal Emacs by default; supply an Emacs executable path to use another installed build.
Normal Emacs configuration is loaded. Preparation uses working Lisp and native Renode grammars with Nix's pinned Python
grammar.

For an existing session, load `.tmp/emacs/setup.el` with `M-x load-file`, then open `.tmp/emacs/review.repl` or the
pinned corpus under `.tmp/corpus/input/`. After Lisp edits, reload the setup and run `M-x normal-mode` in open Renode
buffers. After grammar edits, repeat preparation and restart Emacs to discard cached libraries.

The [brief](brief.md#grammar-and-editor-behavior) owns mode behavior and limitations. Review highlighting, editing and
commenting in your Emacs configuration; automated tests exercise the native parsers and faces.

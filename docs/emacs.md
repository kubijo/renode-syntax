# Using the Emacs modes

Requires Emacs 30.1+ with native Tree-sitter and a runtime accepting grammar ABI 15. The package associates `.repl` and
`.resc` files with `renode-repl-ts-mode` and `renode-resc-ts-mode`.

Use the `integrations::emacs` Just module to prepare or launch a review. Review opens the fixture with the setup
preloaded, using pinned terminal Emacs by default; supply an Emacs executable path to use another installed build.
Normal Emacs configuration is loaded. Preparation uses working Lisp and native Renode grammars with Nix's pinned Python
grammar.

For an existing session, load `.tmp/emacs/setup.el` with `M-x load-file`, then open `.tmp/emacs/review.repl` or the
pinned corpus under `.tmp/corpus/input/`. After Lisp edits, reload the setup and run `M-x normal-mode` in open Renode
buffers. After grammar edits, repeat preparation and restart Emacs to discard cached libraries.

After publishing, replace `COMMIT` below to pin the package and both grammars to the same revision:

```elisp
(let ((revision "COMMIT")
      (repository "https://github.com/kubijo/renode-syntax"))
  (package-vc-install
   `(renode-ts-mode :url ,repository :lisp-dir "integrations/emacs")
   revision)
  (require 'renode-ts-mode)
  (dolist (language '(repl resc))
    (add-to-list 'treesit-language-source-alist
                 (list language repository revision
                       (format "tree-sitter/%s/src" language)))))
```

Run `M-x treesit-install-language-grammar` for `repl` and `resc`; this needs Git and a C compiler. Install a Python
grammar the same way to enable embedded Python highlighting. Without it, Python bodies remain strings.

The [brief](brief.md#grammars-and-editor-support) owns mode behavior and limitations. Review highlighting, editing and
commenting in your Emacs configuration; automated tests exercise the native parsers and faces.

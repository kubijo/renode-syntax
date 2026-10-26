# Renode modes for Emacs

Native Tree-sitter modes for Renode platform descriptions (`.repl`) and monitor scripts (`.resc`), with embedded monitor
and Python highlighting.

Requires Emacs 30.1+ with native Tree-sitter and a runtime accepting grammar ABI 15. Installation needs Git and a C
compiler.

## Install from Git

Install directly from this repository with Emacs's built-in `package-vc-install`; MELPA is not needed. Evaluate this
form once in Emacs to install the Lisp package and register both Renode grammar sources from the same checkout. `nil`
selects the current default-branch commit; replace it with a commit hash to select a fixed revision.

```elisp
(let ((revision nil)
      (repository "https://github.com/kubijo/renode-syntax"))
  (package-vc-install
   `(renode-ts-mode :url ,repository :lisp-dir "integrations/emacs")
   revision)
  (require 'renode-ts-mode)
  (let ((checkout (package-desc-dir (cadr (assq 'renode-ts-mode package-alist)))))
    (dolist (language '(repl resc))
      (add-to-list 'treesit-language-source-alist
                   (list language checkout nil
                         (format "tree-sitter/%s/src" language))))))
```

Then run `M-x treesit-install-language-grammar` once for `repl` and once for `resc`. Open a `.repl` or `.resc` file to
activate `renode-repl-ts-mode` or `renode-resc-ts-mode` automatically.

The grammar installer reuses the installed package's checkout, keeping both grammars at the package's revision without
another download. Keep them at matching revisions when updating.

Embedded Python highlighting uses an installed `python` Tree-sitter grammar; without it, Python bodies remain strings.
Automatic indentation is not provided.

See the [Emacs manual](https://www.gnu.org/software/emacs/manual/html_node/emacs/Fetching-Package-Sources.html) for
repository package management and the [maintainer guide](../../docs/emacs.md) for local review.

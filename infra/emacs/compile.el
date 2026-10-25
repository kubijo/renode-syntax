;;; compile.el --- Compile maintained Lisp outside product directories -*- lexical-binding: t; -*-

(require 'bytecomp)
(let* ((root (file-name-as-directory (getenv "RENODE_SYNTAX_ROOT")))
       (output (expand-file-name ".tmp/emacs/elc/" root))
       (byte-compile-error-on-warn t)
       (byte-compile-dest-file-function
        (lambda (file) (expand-file-name (concat (file-name-base file) ".elc") output))))
  (make-directory output t)
  (add-to-list 'load-path (expand-file-name "integrations/emacs" root))
  (dolist (file
           (append
            (directory-files (expand-file-name "integrations/emacs" root) t "\\.el\\'")
            (directory-files (expand-file-name "infra/emacs" root) t "\\.el\\'")))
    (unless (byte-compile-file file)
      (kill-emacs 1))))

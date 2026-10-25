;;; format.el --- Format maintained Emacs Lisp -*- lexical-binding: t; -*-

(require 'elisp-autofmt)
(setq
 elisp-autofmt-python-bin (pop command-line-args-left)
 elisp-autofmt-cache-directory (expand-file-name ".tmp/cache/elisp-autofmt")
 elisp-autofmt-format-quoted nil)

(dolist (path command-line-args-left)
  (with-temp-buffer
    (insert-file-contents path t)
    (let ((original (buffer-string)))
      (delay-mode-hooks
        (emacs-lisp-mode))
      (check-parens)
      (setq-local
       indent-tabs-mode nil
       fill-column 100)
      (goto-char (point-min))
      (unless (elisp-autofmt-buffer)
        (error "Formatting failed: %s" path))
      (delete-trailing-whitespace)
      (unless (or (bobp) (eq (char-before (point-max)) ?\n))
        (goto-char (point-max))
        (insert "\n"))
      (unless (equal original (buffer-string))
        (write-region (point-min) (point-max) path nil 'silent)))))
(setq command-line-args-left nil)

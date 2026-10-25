;;; renode-ts-mode.el --- Renode platform and monitor modes -*- lexical-binding: t; -*-

;; Copyright (C) 2026 kubijo
;; SPDX-License-Identifier: MIT
;; Author: kubijo
;; Version: 0.1.0
;; Package-Requires: ((emacs "30.1"))
;; Keywords: languages
;; URL: https://github.com/kubijo/renode-syntax

;;; Commentary:
;; Tree-sitter modes for Renode .repl and .resc files.  Install the repl and resc
;; grammars before enabling the modes.  A Python grammar enables embedded Python.

;;; Code:

(require 'cl-lib)
(require 'treesit)
(require 'python)
(require 'renode-ts-data)

(defvar-local renode-ts--language nil)
(defvar-local renode-ts--primary nil)
(defvar-local renode-ts--embedded nil)
(defvar-local renode-ts--tick nil)
(defvar-local renode-ts--python nil)

(defun renode-ts--captures (parser query)
  "Return nodes captured by QUERY in PARSER."
  (mapcar #'cdr (treesit-query-capture (treesit-parser-root-node parser) query)))

(defun renode-ts--range (node)
  "Return NODE's buffer range."
  (cons (treesit-node-start node) (treesit-node-end node)))

(defun renode-ts--child-ranges (parser node)
  "Return NODE's ranges without the gaps excluded by PARSER."
  (let ((span (renode-ts--range node)))
    (mapcan
     (lambda (range)
       (let ((start (max (car span) (car range)))
             (end (min (cdr span) (cdr range))))
         (when (< start end)
           (list (cons start end)))))
     (or (treesit-parser-included-ranges parser) (list span)))))

(defun renode-ts--update-ranges (_beg _end)
  "Update independent embedded parsers after a buffer edit.
Monitor fragments share a parser within their body, excluding platform comments.
Different bodies and Python snippets never share parser state."
  (unless (eql renode-ts--tick (buffer-chars-modified-tick))
    (let ((remaining renode-ts--embedded)
          active)
      (cl-labels
       ((embed
         (language ranges)
         (when ranges
           (let ((parser
                  (or (cl-find-if
                       (lambda (candidate)
                         (eq (treesit-parser-language candidate) language))
                       remaining)
                      (treesit-parser-create language nil t))))
             (setq remaining (delq parser remaining))
             (treesit-parser-set-included-ranges parser ranges)
             (push parser active)
             parser)))
        (monitor
         (parser)
         (when renode-ts--python
           (dolist (node (renode-ts--captures parser '((python_body) @body)))
             (embed 'python (renode-ts--child-ranges parser node))))
         (dolist (node (renode-ts--captures parser '((execution_body) @body)))
           (monitor (embed 'resc (renode-ts--child-ranges parser node))))))
       (if (eq renode-ts--language 'resc)
           (monitor renode-ts--primary)
         (dolist (body (renode-ts--captures renode-ts--primary '((monitor_body) @body)))
           (let ((ranges
                  (mapcar
                   #'renode-ts--range
                   (cl-remove-if-not
                    (lambda (child)
                      (equal (treesit-node-type child) "monitor_text"))
                    (treesit-node-children body t)))))
             (when ranges
               (monitor (embed 'resc ranges)))))
         (when renode-ts--python
           (dolist (node
                    (renode-ts--captures
                     renode-ts--primary
                     '((property value: (multiline_string (multiline_content) @body)))))
             (let* ((property (treesit-node-parent (treesit-node-parent node)))
                    (name (treesit-node-child-by-field-name property "name")))
               (when (equal (treesit-node-text name t) "script")
                 (embed 'python (list (renode-ts--range node))))))))
       (mapc #'treesit-parser-delete remaining)
       (setq
        renode-ts--embedded (nreverse active)
        renode-ts--tick (buffer-chars-modified-tick))))))

(defun renode-ts--parser-at (position)
  "Return the innermost parser covering POSITION."
  (renode-ts--update-ranges (point-min) (point-max))
  (or (cl-find-if
       (lambda (parser)
         (cl-some
          (lambda (range) (<= (car range) position (1- (cdr range))))
          (treesit-parser-included-ranges parser)))
       (reverse renode-ts--embedded))
      renode-ts--primary))

(defun renode-ts--language-at (position)
  "Return the language at POSITION."
  (treesit-parser-language (renode-ts--parser-at position)))

(defun renode-ts--fontify-command (node override start end &rest _)
  "Fontify command NODE within START and END using OVERRIDE."
  (treesit-fontify-with-override
   (treesit-node-start node) (treesit-node-end node)
   (if (member (treesit-node-text node t) renode-ts--commands)
       'font-lock-builtin-face
     'font-lock-function-call-face)
   override start end))

(defun renode-ts--fontify-content (node override start end &rest _)
  "Fontify non-Python multiline NODE within START and END using OVERRIDE."
  (unless (eq (renode-ts--language-at (treesit-node-start node)) 'python)
    (treesit-fontify-with-override
     (treesit-node-start node) (treesit-node-end node) 'font-lock-string-face override start end)))

(defun renode-ts--font-lock-settings ()
  "Return font-lock settings for Renode and available embedded languages."
  (append
   (when (eq renode-ts--language 'repl)
     (treesit-font-lock-rules
      :language 'repl
      :feature 'comment '((comment) @font-lock-comment-face)
      :language 'repl
      :feature 'string
      '((string)
        @font-lock-string-face
        "'''"
        @font-lock-string-face
        (multiline_end)
        @font-lock-string-face
        (multiline_content)
        @renode-ts--fontify-content)
      :language 'repl
      :feature 'constant
      '([(boolean) (none) (empty) (enum)]
        @font-lock-constant-face
        [(number) (unsigned)]
        @font-lock-number-face)
      :language 'repl
      :feature 'keyword
      `([,@renode-ts--keywords]
        @font-lock-keyword-face
        [(monitor_keyword) (monitor_modifier)]
        @font-lock-keyword-face)
      :language 'repl
      :feature 'definition
      '((entry name: (identifier) @font-lock-variable-name-face)
        (property name: (identifier) @font-lock-property-name-face)
        (type_name)
        @font-lock-type-face)))
   (treesit-font-lock-rules
    :language 'resc
    :feature
    'comment
    '((comment) @font-lock-comment-face)
    :language 'resc
    :feature
    'string
    '([(string) (string_content) (multiline_delimiter) (execution_delimiter)]
      @font-lock-string-face
      (path)
      @font-lock-string-face
      (python_body)
      @renode-ts--fontify-content)
    :language 'resc
    :feature
    'constant
    '([(number) (range)] @font-lock-number-face [(boolean) (null)] @font-lock-constant-face)
    :language 'resc
    :feature
    'keyword
    '([(macro_keyword) (python_keyword)] @font-lock-keyword-face)
    :language 'resc
    :feature
    'definition
    '((command name: (literal) @renode-ts--fontify-command)
      (variable)
      @font-lock-variable-use-face
      (named_argument name: (literal) @font-lock-property-name-face)
      (macro_definition name: (_) @font-lock-function-name-face)))
   (when renode-ts--python
     ;; Ask the installed Python mode for its settings rather than copying its rules.
     (with-temp-buffer
       (let ((python-indent-guess-indent-offset nil))
         (delay-mode-hooks
           (python-ts-mode)))
       treesit-font-lock-settings))))

(defun renode-ts--name (node)
  "Return NODE's name for navigation."
  (treesit-node-text (treesit-node-child-by-field-name node "name") t))

(defun renode-ts--comment-context ()
  "Set comment syntax for the language at point or the region start."
  (let ((language
         (save-excursion
           (when (use-region-p)
             (goto-char (region-beginning)))
           (skip-chars-forward " \t" (line-end-position))
           (renode-ts--language-at (point)))))
    (setq-local
     comment-start
     (concat
      (if (eq language 'repl)
          renode-ts--repl-comment
        renode-ts--resc-comment)
      " ")
     comment-start-skip (concat (regexp-quote (string-trim-right comment-start)) "+[ \t]*"))))

(defun renode-ts-comment-dwim (argument)
  "Comment using the language at point or the region start, passing ARGUMENT."
  (interactive "*P")
  (renode-ts--comment-context)
  (comment-dwim argument))

(defun renode-ts--imenu ()
  "Index host definitions independently of the embedded parser at point."
  (list
   (cons
    (if (eq renode-ts--language 'repl)
        "Devices"
      "Macros")
    (mapcar
     (lambda (node) (cons (renode-ts--name node) (treesit-node-start node)))
     (renode-ts--captures
      renode-ts--primary
      (if (eq renode-ts--language 'repl)
          '((entry) @definition)
        '((macro_definition) @definition)))))))

(defun renode-ts--setup (language)
  "Configure the current buffer for LANGUAGE."
  (unless (and (treesit-ready-p language) (treesit-ready-p 'resc))
    (user-error "Install repl and resc with M-x treesit-install-language-grammar"))
  (setq-local
   renode-ts--language language
   renode-ts--primary (treesit-parser-create language)
   renode-ts--python (treesit-ready-p 'python t)
   treesit-language-at-point-function #'renode-ts--language-at
   treesit-range-settings (treesit-range-rules #'renode-ts--update-ranges)
   treesit-font-lock-settings (renode-ts--font-lock-settings)
   treesit-font-lock-feature-list
   '((comment string)
     (keyword constant)
     (definition
      assignment builtin decorator escape-sequence function number property type variable))
   treesit-defun-type-regexp
   (if (eq language 'repl)
       "^entry$"
     "^macro_definition$")
   treesit-defun-name-function #'renode-ts--name
   treesit-simple-imenu-settings
   (if (eq language 'repl)
       '(("Devices" "^entry$" nil renode-ts--name))
     '(("Macros" "^macro_definition$" nil renode-ts--name)))
   comment-start
   (concat
    (if (eq language 'repl)
        renode-ts--repl-comment
      renode-ts--resc-comment)
    " ")
   comment-end ""
   comment-use-syntax nil
   comment-start-skip (concat (regexp-quote (string-trim-right comment-start)) "+[ \t]*")
   indent-tabs-mode nil)
  (treesit-major-mode-setup)
  (add-hook 'post-command-hook #'renode-ts--comment-context nil t)
  (keymap-set (current-local-map) "M-;" #'renode-ts-comment-dwim)
  (setq-local
   treesit-primary-parser renode-ts--primary
   imenu-create-index-function #'renode-ts--imenu))

;;;###autoload
(define-derived-mode
 renode-repl-ts-mode
 prog-mode
 "Renode Platform"
 "Major mode for Renode platform descriptions using Tree-sitter."
 (renode-ts--setup 'repl))

;;;###autoload
(define-derived-mode
 renode-resc-ts-mode
 prog-mode
 "Renode Script"
 "Major mode for Renode monitor scripts using Tree-sitter."
 (renode-ts--setup 'resc))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.repl\\'" . renode-repl-ts-mode))
;;;###autoload
(add-to-list 'auto-mode-alist '("\\.resc\\'" . renode-resc-ts-mode))

(provide 'renode-ts-mode)
;;; renode-ts-mode.el ends here

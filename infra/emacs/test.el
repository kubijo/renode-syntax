;;; test.el --- Exercise Renode through native Emacs Tree-sitter -*- lexical-binding: t; -*-

(require 'ert)
(require 'imenu)
(require 'renode-ts-mode)

(defmacro renode-test--buffer (source mode &rest body)
  "Insert SOURCE, enable MODE and evaluate BODY in a temporary buffer."
  (declare (indent 2) (debug t))
  `(with-temp-buffer
     (insert ,source)
     (let ((treesit-font-lock-level 4))
       (,mode))
     (font-lock-ensure)
     ,@body))

(defun renode-test--position (text)
  "Return the start of TEXT in the current buffer."
  (save-excursion
    (goto-char (point-min))
    (search-forward text)
    (- (point) (length text))))

(defun renode-test--face (text)
  "Return the face at TEXT."
  (get-text-property (renode-test--position text) 'face))

(defun renode-test--language (text)
  "Return the embedded language at TEXT."
  (treesit-language-at (renode-test--position text)))

(ert-deftest renode-test-native-grammars ()
  (dolist (language '(repl resc python))
    (should (treesit-language-available-p language))))

(ert-deftest renode-test-setup-reloads-working-source ()
  (let* ((root (getenv "RENODE_SYNTAX_ROOT"))
         (load-path (remove (expand-file-name "integrations/emacs" root) load-path)))
    (cl-letf (((symbol-function 'renode-repl-ts-mode) #'ignore))
      (load-file (expand-file-name ".tmp/emacs/setup.el" root))
      (with-temp-buffer
        (renode-repl-ts-mode)
        (should (eq major-mode 'renode-repl-ts-mode))))))

(ert-deftest renode-test-pinned-corpus ()
  (let* ((root (file-name-as-directory (getenv "RENODE_SYNTAX_ROOT")))
         (files
          (with-temp-buffer
            (insert-file-contents (expand-file-name ".tmp/corpus/files0" root))
            (split-string (buffer-string) "\0" t))))
    (should files)
    (dolist (file files)
      (ert-info
       ((format "Native corpus: %s" file))
       (with-temp-buffer
         (insert-file-contents (expand-file-name file root))
         (if (string-suffix-p ".repl" file)
             (renode-repl-ts-mode)
           (renode-resc-ts-mode))
         (font-lock-ensure)
         (dolist (parser (cons renode-ts--primary renode-ts--embedded))
           (unless (eq (treesit-parser-language parser) 'python)
             (should-not (treesit-node-check (treesit-parser-root-node parser) 'has-error)))))))
    (message "Fontified %s pinned files in native Emacs" (length files))))

(ert-deftest renode-test-review-fixture-and-comment-gap ()
  (renode-test--buffer (with-temp-buffer
                         (insert-file-contents
                          (expand-file-name ".tmp/emacs/review.repl" (getenv "RENODE_SYNTAX_ROOT")))
                         (buffer-string))
                       renode-repl-ts-mode
    (should (= 4 (cl-count 'resc renode-ts--embedded :key #'treesit-parser-language)))
    (should (= 3 (cl-count 'python renode-ts--embedded :key #'treesit-parser-language)))
    (dolist (parser (cons renode-ts--primary renode-ts--embedded))
      (should-not (treesit-node-check (treesit-parser-root-node parser) 'has-error)))
    (should (eq (renode-test--language "for key") 'python))
    (should (eq (renode-test--face "for key") 'font-lock-keyword-face))
    (should (eq (renode-test--language "// Platform comment") 'repl))
    (should (eq (renode-test--face "// Platform comment") 'font-lock-comment-face))
    (should (eq (renode-test--language "echo \"monitor syntax") 'resc))
    (should (eq (renode-test--face "echo \"monitor syntax") 'font-lock-builtin-face))
    (should (eq (renode-test--language "after:") 'repl))
    (should (assoc "Devices" (imenu--make-index-alist t)))))

(ert-deftest renode-test-python-property-and-opaque-string ()
  (renode-test--buffer "p:\n    script: '''return 42'''\n    other: '''return 0'''\nnext:\n"
      renode-repl-ts-mode
    (should (eq (renode-test--language "return 42") 'python))
    (should (eq (renode-test--face "return 42") 'font-lock-keyword-face))
    (should (eq (renode-test--language "return 0") 'repl))
    (should (eq (renode-test--face "return 0") 'font-lock-string-face))
    (should (eq (renode-test--language "next:") 'repl))))

(ert-deftest renode-test-resc-structure-and-execution ()
  (renode-test--buffer
      "$name=1\nmacro reset\n\"\"\"\n    echo \"reset\"\n\"\"\"\necho `help`\npython \"\"\"\nprint(42)\n\"\"\"\n"
      renode-resc-ts-mode
    (should (eq (renode-test--language "help") 'resc))
    (should (eq (renode-test--face "help") 'font-lock-builtin-face))
    (should (eq (renode-test--language "print(42)") 'python))
    (should (eq (renode-test--face "macro") 'font-lock-keyword-face))
    (should (eq (renode-test--face "reset\n") 'font-lock-function-name-face))
    (should (assoc "Macros" (imenu--make-index-alist t)))))

(ert-deftest renode-test-nested-execution-excludes-platform-comments ()
  (renode-test--buffer "p:\n    init:\n        echo `help /* parent comment */; help`\nnext:\n"
      renode-repl-ts-mode
    (should (= (length renode-ts--embedded) 2))
    (should (eq (renode-test--language "/* parent") 'repl))
    (should (eq (renode-test--face "/* parent") 'font-lock-comment-face))
    (dolist (parser (cons renode-ts--primary renode-ts--embedded))
      (should-not (treesit-node-check (treesit-parser-root-node parser) 'has-error)))))

(ert-deftest renode-test-independent-python-blocks ()
  (renode-test--buffer "python \"\"\"\ndef broken(\n\"\"\"\npython \"\"\"\nvalue = 42\n\"\"\"\n"
      renode-resc-ts-mode
    (let ((parsers
           (cl-remove-if-not
            (lambda (parser) (eq (treesit-parser-language parser) 'python)) renode-ts--embedded)))
      (should (= (length parsers) 2))
      (should (treesit-node-check (treesit-parser-root-node (car parsers)) 'has-error))
      (should-not (treesit-node-check (treesit-parser-root-node (cadr parsers)) 'has-error)))))

(ert-deftest renode-test-incremental-ranges-and-removal ()
  (renode-test--buffer
      "p:\n    init:\n        echo \"a\" // parent\n        python \"\"\"\nprint(1)\n\"\"\"\nnext:\n"
      renode-repl-ts-mode
    (let ((parser (renode-ts--parser-at (renode-test--position "print(1)"))))
      (goto-char (renode-test--position "// parent"))
      (insert "// another comment\n        echo \"b\" ")
      (font-lock-flush)
      (font-lock-ensure)
      (should (eq parser (renode-ts--parser-at (renode-test--position "print(1)"))))
      (should (eq (renode-test--face "print(1)") 'font-lock-builtin-face))
      (goto-char (renode-test--position "python"))
      (delete-char (length "python"))
      (insert "echo")
      (font-lock-flush)
      (font-lock-ensure)
      (should-not (memq parser renode-ts--embedded))
      (should (eq (renode-test--language "print(1)") 'resc))
      (should (eq (renode-test--face "print(1)") 'font-lock-string-face)))))

(ert-deftest renode-test-missing-optional-python ()
  (renode-test--buffer "python \"\"\"\nprint(1)\n\"\"\"\n" renode-resc-ts-mode
    (setq
     renode-ts--python nil
     renode-ts--tick nil)
    (renode-ts--update-ranges (point-min) (point-max))
    (should-not renode-ts--embedded)
    (should (eq (renode-test--language "print(1)") 'resc))))

(ert-deftest renode-test-comments-follow-embedded-language ()
  (renode-test--buffer "p:\n    script: '''\nvalue = 42\n'''\n" renode-repl-ts-mode
    (goto-char (renode-test--position "value"))
    (set-mark (point))
    (end-of-line)
    (activate-mark)
    (let ((transient-mark-mode t))
      (call-interactively (key-binding (kbd "M-;"))))
    (should (string-match-p "# value = 42" (buffer-string)))))

(ert-deftest renode-test-comment-line-follows-point ()
  (dolist
      (example
       '((renode-repl-ts-mode "p:\n    script: '''\nvalue = 42\n'''\n" "value" "#")
         (renode-repl-ts-mode "p:\n    init:\n        python \"\"\"\nvalue = 42\n\"\"\"\n" "value" "#")
         (renode-resc-ts-mode "python \"\"\"\nvalue = 42\n\"\"\"\n" "value" "#")
         (renode-repl-ts-mode "p:\n    init:\n        echo 42\n" "echo" "#")
         (renode-repl-ts-mode "p:\n    size: 42\n" "size" "//")))
    (with-temp-buffer
      (insert (nth 1 example))
      (funcall (car example))
      (font-lock-ensure)
      (goto-char (renode-test--position (nth 2 example)))
      (beginning-of-line)
      (let ((original (buffer-string)))
        (run-hooks 'post-command-hook)
        (comment-line 1)
        (should
         (string-match-p
          (concat (regexp-quote (nth 3 example)) " " (nth 2 example)) (buffer-string)))
        (goto-char (point-min))
        (search-forward (concat (nth 3 example) " " (nth 2 example)))
        (run-hooks 'post-command-hook)
        (comment-line 1)
        (should (equal original (buffer-string)))))))

(ert-deftest renode-test-mode-discovery-and-cleanup ()
  (dolist (entry '(("board.repl" . renode-repl-ts-mode) ("script.resc" . renode-resc-ts-mode)))
    (with-temp-buffer
      (setq buffer-file-name (car entry))
      (set-auto-mode)
      (should (eq major-mode (cdr entry)))
      (fundamental-mode)
      (should-not (memq #'renode-ts--comment-context post-command-hook))
      (should-not (treesit-parser-list nil nil t)))))

;;; test.el ends here

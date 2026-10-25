(list
  (left_bracket) @open
  (right_bracket) @close)

(execution
  open: (execution_delimiter) @open
  close: (execution_delimiter) @close)

(macro_body
  open: (multiline_delimiter) @open
  close: (multiline_delimiter) @close)

(python_block
  (multiline_delimiter) @open
  (multiline_delimiter) @close)

(multiline_string
  (multiline_delimiter) @open
  (multiline_delimiter) @close)

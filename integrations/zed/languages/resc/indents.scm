(macro_body
  open: (multiline_delimiter) @start
  close: (multiline_delimiter) @end) @indent

(python_block
  (multiline_delimiter) @start
  (multiline_delimiter) @end) @indent

(list
  (left_bracket) @start
  (right_bracket) @end) @indent

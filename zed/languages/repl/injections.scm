; Zed joins fragments by their containing body, excluding platform comments.
((monitor_body (monitor_text) @injection.content) @injection.host
  (#set! injection.language "Renode Script"))

((property
  name: (identifier) @_name
  value: (multiline_string (multiline_content) @injection.content))
  (#eq? @_name "script")
  (#set! injection.language "python"))

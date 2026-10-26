(comment) @comment
(command name: (literal) @function)
(macro_definition name: (_) @function)
(variable) @variable
(named_argument name: (literal) @variable.parameter)
(string) @string
(multiline_string) @string
(path) @string.special
(variable_path) @string.special
(number) @number
(range) @number
(boolean) @boolean
(null) @constant.builtin
(assignment_operator) @operator
(multiline_delimiter) @punctuation.delimiter
(execution_delimiter) @punctuation.special
[(left_bracket) (right_bracket)] @punctuation.bracket
[(comma) (command_split)] @punctuation.delimiter

[(macro_keyword) (python_keyword)] @keyword

((command name: (literal) @keyword)
  (#any-of? @keyword
    "alias"
    "allowPrivates"
    "analyzers"
    "autoSave"
    "createPlatform"
    "currentTime"
    "displayImage"
    "execute"
    "help"
    "include"
    "lastLog"
    "log"
    "logFile"
    "logLevel"
    "logNetwork"
    "mach"
    "macro"
    "numbersMode"
    "path"
    "pause"
    "peripherals"
    "printenv"
    "python"
    "quit"
    "repeatLast"
    "require"
    "resd"
    "reverseExecMode"
    "runMacro"
    "set"
    "setAndRevertAfter"
    "showAnalyzer"
    "start"
    "string"
    "tags"
    "using"
    "verboseMode"
    "version"
    "watch"
    "console_log"
    "dump"
    "dump_file"
    "echo"
    "get_environ"
    "if"
    "next_value"
    "print"
    "pyprint"
    "sleep"
    "str_contains"
    "uart_connect"))

//! Detect unfinished contexts by checking ordinary source appended after each corpus file.

use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
    process::ExitCode,
    str::FromStr,
};

use syntect::{
    highlighting::ScopeSelectors,
    parsing::{ParseState, ScopeStack, SyntaxSet},
};

use crate::{load_syntaxes, scope_stacks};

struct Probe {
    line: &'static str,
    spans: &'static [(&'static str, &'static str)],
}

const PLATFORM: &[Probe] = &[
    Probe {
        line: "renodeSyntaxSentinel: Syntax.Sentinel @ sysbus 0x1234\n",
        spans: &[
            ("renodeSyntaxSentinel", "entity.name.variable.renode-repl"),
            ("Syntax.Sentinel", "support.class.renode-repl"),
            ("0x1234", "constant.numeric.integer.hexadecimal.renode-repl"),
        ],
    },
    Probe {
        line: "    sentinel: 314159\n",
        spans: &[
            ("sentinel", "variable.other.member.renode-repl"),
            ("314159", "constant.numeric.decimal.renode-repl"),
        ],
    },
];

const MONITOR: &[Probe] = &[Probe {
    line: "sysbus ReadDoubleWord 0x1234\n",
    spans: &[
        ("sysbus", "variable.other.object.renode-resc"),
        ("ReadDoubleWord", "variable.function.renode-resc"),
        ("0x1234", "constant.numeric.integer.hexadecimal.renode-resc"),
    ],
}];

fn paths(contents: &str) -> Result<Vec<PathBuf>, String> {
    let Some(body) = contents.strip_suffix('\0') else {
        return Err("corpus file list is empty or lacks its final NUL".into());
    };
    let mut seen = HashSet::new();
    let mut result = Vec::new();
    for name in body.split('\0') {
        let path = PathBuf::from(name);
        if !matches!(
            path.extension().and_then(|value| value.to_str()),
            Some("repl" | "resc")
        ) {
            return Err(format!("unsupported corpus input: {name:?}"));
        }
        if !seen.insert(path.clone()) {
            return Err(format!("duplicate corpus input: {name:?}"));
        }
        result.push(path);
    }
    Ok(result)
}

fn inspect(set: &SyntaxSet, extension: &str, contents: &str) -> Result<Vec<String>, String> {
    let syntax = set
        .find_syntax_by_extension(extension)
        .ok_or_else(|| format!("missing {extension} grammar"))?;
    let probes = match extension {
        "repl" => PLATFORM,
        "resc" => MONITOR,
        _ => return Err(format!("unsupported corpus language {extension}")),
    };
    let mut state = ParseState::new(syntax);
    let mut stack = ScopeStack::new();
    let mut line_number = 0;
    // Appending real newlines lets a valid EOF line comment end and an indented monitor block pop.
    // No quote, brace, or comment terminator is supplied: unfinished contexts must remain visible.
    for line in format!("{contents}\n\n").split_inclusive('\n') {
        line_number += 1;
        for (_, operation) in state
            .parse_line(line, set)
            .map_err(|error| format!("line {line_number}: {error}"))?
        {
            stack.apply(&operation).map_err(|error| error.to_string())?;
        }
    }
    let mut failures = Vec::new();
    for probe in probes {
        line_number += 1;
        let scopes = scope_stacks(&mut state, &mut stack, set, probe.line)?;
        for &(needle, role) in probe.spans {
            let expected = format!("source.renode.{extension} {role} - comment - string - source.python - meta.block - meta.interpolation");
            let selector =
                ScopeSelectors::from_str(&expected).map_err(|error| error.to_string())?;
            let byte = probe
                .line
                .find(needle)
                .expect("BUG: probe span is absent from its line");
            let start = probe.line[..byte].chars().count();
            let end = start + needle.chars().count();
            if let Some(actual) = scopes[start..end]
                .iter()
                .find(|scope| selector.does_match(scope.as_slice()).is_none())
            {
                let actual = actual
                    .as_slice()
                    .iter()
                    .map(|scope| scope.build_string())
                    .collect::<Vec<_>>()
                    .join(" ");
                failures.push(format!(
                    "{line_number}: sentinel {needle:?}: expected {expected:?}, got {actual:?}"
                ));
            }
        }
    }
    Ok(failures)
}

fn check(syntax_dir: &Path, manifest: &Path) -> Result<bool, String> {
    let inputs = paths(
        &fs::read_to_string(manifest)
            .map_err(|error| format!("{}: {error}", manifest.display()))?,
    )?;
    let set = load_syntaxes(&[syntax_dir.to_path_buf()]);
    let (mut repl, mut resc, mut failed) = (0, 0, 0);
    for path in &inputs {
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .expect("validated corpus extension");
        if extension == "repl" {
            repl += 1;
        } else {
            resc += 1;
        }
        let contents =
            fs::read_to_string(path).map_err(|error| format!("{}: {error}", path.display()))?;
        let failures = inspect(&set, extension, &contents)
            .map_err(|error| format!("{}: {error}", path.display()))?;
        if !failures.is_empty() {
            failed += 1;
            for failure in failures {
                println!("{}:{failure}", path.display());
            }
        }
    }
    println!(
        "{} corpus files ({repl} repl, {resc} resc), {failed} files with leaks",
        inputs.len()
    );
    Ok(failed == 0)
}

pub(super) fn run(syntax_dir: &Path, manifest: &Path) -> ExitCode {
    match check(syntax_dir, manifest) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(error) => {
            eprintln!("corpus: {error}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use std::{env, path::PathBuf, sync::OnceLock};

    use syntect::parsing::SyntaxSet;

    use super::{inspect, paths};
    use crate::load_syntaxes;

    fn syntax_set() -> &'static SyntaxSet {
        static SET: OnceLock<SyntaxSet> = OnceLock::new();
        SET.get_or_init(|| {
            let root = PathBuf::from(
                env::var_os("RENODE_SYNTAX_ROOT").expect("run tests in the Nix shell"),
            );
            load_syntaxes(&[root.join("integrations/sublime")])
        })
    }

    #[test]
    fn valid_eof_line_comments_and_crlf_do_not_leak() {
        for (extension, contents) in [
            ("repl", "// end"),
            ("resc", "# end"),
            ("resc", "echo 1\r\n# end"),
            ("repl", ""),
        ] {
            assert!(
                inspect(syntax_set(), extension, contents)
                    .unwrap()
                    .is_empty(),
                "{extension}: {contents:?}"
            );
        }
    }

    #[test]
    fn indented_monitor_and_balanced_embeddings_do_not_leak() {
        for (extension, contents) in [
            ("repl", "init:\n    sysbus LoadELF @test.elf"),
            (
                "repl",
                "cpu: CPU.Example @ sysbus 0\n    script: '''\nx = 1\n'''",
            ),
            ("resc", "python \"\"\"\nprint('ok')\n\"\"\""),
            (
                "resc",
                "macro test\n\"\"\"\nsysbus ReadDoubleWord 0\n\"\"\"",
            ),
        ] {
            assert!(
                inspect(syntax_set(), extension, contents)
                    .unwrap()
                    .is_empty(),
                "{extension}: {contents:?}"
            );
        }
    }

    #[test]
    fn unfinished_strings_comments_and_embeds_are_detected() {
        for (extension, contents) in [
            ("repl", "/* unfinished"),
            ("repl", "value: \"unfinished"),
            (
                "repl",
                "cpu: CPU.Example @ sysbus 0\n    script: '''\nx = 1",
            ),
            ("resc", "echo \"unfinished"),
            ("resc", "python \"\"\"\nx = 1"),
        ] {
            assert!(
                !inspect(syntax_set(), extension, contents)
                    .unwrap()
                    .is_empty(),
                "{extension}: {contents:?}"
            );
        }
    }

    #[test]
    fn unfinished_macro_and_brace_contexts_are_detected() {
        for (extension, contents) in [
            ("resc", "macro test\n\"\"\"\necho 1"),
            ("repl", "init: { sysbus ReadDoubleWord 0"),
        ] {
            assert!(
                !inspect(syntax_set(), extension, contents)
                    .unwrap()
                    .is_empty(),
                "{extension}: {contents:?}"
            );
        }
    }

    #[test]
    fn each_file_starts_with_a_fresh_parse_state() {
        assert!(!inspect(syntax_set(), "resc", "python \"\"\"\nx = 1")
            .unwrap()
            .is_empty());
        assert!(inspect(syntax_set(), "resc", "echo 1").unwrap().is_empty());
    }

    #[test]
    fn file_list_rejects_missing_empty_duplicate_or_foreign_entries() {
        for contents in ["", "input.repl", "\0", "a.repl\0a.repl\0", "a.py\0"] {
            assert!(paths(contents).is_err(), "{contents:?}");
        }
        assert_eq!(
            paths("file with spaces.repl\0monitor.resc\0")
                .unwrap()
                .len(),
            2
        );
    }
}

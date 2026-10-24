//! Runs Sublime-style `syntax_test_*` files against syntect, the engine bat uses.
//!
//! Usage: `syntax-test <dir>...` loads every grammar under the dirs
//! on top of syntect's defaults, then runs every test file found there.
//! Unlike Sublime, the header's grammar is resolved by file name,
//! since the `Packages/…` prefix depends on what the clone is called.
//! Assertion lines may be indented, so they can sit inside indentation-scoped blocks.

use std::{
    env, fs,
    path::{Path, PathBuf},
    process::ExitCode,
    str::FromStr,
};

use syntect::{
    highlighting::ScopeSelectors,
    parsing::{ParseState, ScopeStack, SyntaxDefinition, SyntaxSet},
};

fn main() -> ExitCode {
    let dirs: Vec<PathBuf> = env::args().skip(1).map(PathBuf::from).collect();
    if dirs.is_empty() {
        eprintln!("usage: syntax-test <dir>...");
        return ExitCode::FAILURE;
    }

    let mut builder = SyntaxSet::load_defaults_newlines().into_builder();
    let mut files = Vec::new();
    for dir in &dirs {
        builder
            .add_from_folder(dir, true)
            .unwrap_or_else(|e| panic!("loading grammars from {}: {e}", dir.display()));
        collect_files(dir, &mut files);
    }
    let set = builder.build();

    let grammars: Vec<&PathBuf> = files
        .iter()
        .filter(|p| p.extension().is_some_and(|e| e == "sublime-syntax"))
        .collect();
    let tests: Vec<&PathBuf> = files
        .iter()
        .filter(|p| file_name(p).starts_with("syntax_test_"))
        .collect();

    let (mut assertions, mut failures) = (0, 0);
    for test in &tests {
        let (run, failed) = run_test(&set, &grammars, test);
        assertions += run;
        failures += failed;
    }
    println!(
        "{} files, {assertions} assertions, {failures} failed",
        tests.len()
    );
    if failures == 0 && assertions > 0 {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn collect_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).unwrap_or_else(|e| panic!("reading {}: {e}", dir.display())) {
        let path = entry
            .expect("BUG: directory entry vanished mid-iteration")
            .path();
        if path.is_dir() {
            collect_files(&path, out);
        } else {
            out.push(path);
        }
    }
}

fn file_name(path: &Path) -> &str {
    path.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default()
}

/// Returns (assertions run, assertions failed).
fn run_test(set: &SyntaxSet, grammars: &[&PathBuf], test: &Path) -> (usize, usize) {
    let contents =
        fs::read_to_string(test).unwrap_or_else(|e| panic!("reading {}: {e}", test.display()));
    let header = contents.lines().next().unwrap_or_default();
    let Some((token, rest)) = header.split_once("SYNTAX TEST") else {
        println!("{}: missing SYNTAX TEST header", test.display());
        return (0, 1);
    };
    let token = token.trim();
    let grammar_name = rest
        .trim()
        .trim_matches('"')
        .rsplit('/')
        .next()
        .unwrap_or_default();
    let Some(grammar) = grammars.iter().find(|p| file_name(p) == grammar_name) else {
        println!("{}: grammar {grammar_name} not found", test.display());
        return (0, 1);
    };
    let definition =
        SyntaxDefinition::load_from_str(&fs::read_to_string(grammar).unwrap(), true, None)
            .unwrap_or_else(|e| panic!("parsing {}: {e}", grammar.display()));
    let syntax = set
        .find_syntax_by_name(&definition.name)
        .expect("BUG: grammar loaded from the same dirs");

    let mut state = ParseState::new(syntax);
    let mut stack = ScopeStack::new();
    let mut tested: Vec<ScopeStack> = Vec::new();
    let mut tested_line_no = 0;
    let (mut run, mut failed) = (0, 0);

    for (index, line) in contents.split_inclusive('\n').enumerate() {
        let char_stacks = scope_stacks(&mut state, &mut stack, set, line);
        let Some(assertion) = parse_assertion(line, token) else {
            tested = char_stacks;
            tested_line_no = index + 1;
            continue;
        };
        let selector = ScopeSelectors::from_str(assertion.selector)
            .unwrap_or_else(|e| panic!("{}:{}: bad selector: {e:?}", test.display(), index + 1));
        let misses: Vec<usize> = assertion
            .columns
            .iter()
            .copied()
            .filter(|&column| {
                tested
                    .get(column)
                    .is_none_or(|s| selector.does_match(s.as_slice()).is_none())
            })
            .collect();
        run += assertion.columns.len();
        failed += misses.len();
        if let Some(&column) = misses.first() {
            let actual = tested
                .get(column)
                .map_or("<past end of line>".to_owned(), |s| {
                    s.as_slice()
                        .iter()
                        .map(|scope| scope.build_string())
                        .collect::<Vec<_>>()
                        .join(" ")
                });
            println!(
                "{}:{tested_line_no}:{}: expected `{}`, got `{actual}` ({} of {} columns)",
                test.display(),
                column + 1,
                assertion.selector,
                misses.len(),
                assertion.columns.len(),
            );
        }
    }
    (run, failed)
}

/// Parses one line and returns the scope stack in effect at each character.
fn scope_stacks(
    state: &mut ParseState,
    stack: &mut ScopeStack,
    set: &SyntaxSet,
    line: &str,
) -> Vec<ScopeStack> {
    let ops = state.parse_line(line, set).expect("parse line");
    let mut by_byte = Vec::with_capacity(line.len());
    let mut ops = ops.iter().peekable();
    for byte in 0..line.len() {
        while let Some((_, op)) = ops.next_if(|(at, _)| *at <= byte) {
            stack.apply(op).expect("apply scope op");
        }
        by_byte.push(stack.clone());
    }
    for (_, op) in ops {
        stack.apply(op).expect("apply scope op");
    }
    line.char_indices()
        .map(|(byte, _)| by_byte[byte].clone())
        .collect()
}

struct Assertion<'a> {
    columns: Vec<usize>,
    selector: &'a str,
}

fn parse_assertion<'a>(line: &'a str, token: &str) -> Option<Assertion<'a>> {
    let line = line.trim_end();
    let indent = line.len() - line.trim_start().len();
    let after_token = line.trim_start().strip_prefix(token)?;
    let body = after_token.trim_start();
    if let Some(selector) = body.strip_prefix("<-") {
        return Some(Assertion {
            columns: vec![line[..indent].chars().count()],
            selector: selector.trim(),
        });
    }
    if !body.starts_with('^') {
        return None;
    }
    let start = line.chars().position(|c| c == '^')?;
    let carets = line.chars().skip(start).take_while(|&c| c == '^').count();
    let selector = line
        .trim_start_matches(|c| c != '^')
        .trim_start_matches('^')
        .trim();
    Some(Assertion {
        columns: (start..start + carets).collect(),
        selector,
    })
}

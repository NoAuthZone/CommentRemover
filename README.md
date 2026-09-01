<div align="center">

# CommentRemover

**Strip code comments from an entire project, across 155 file types — without touching a single line of real code.**

[![Version](https://img.shields.io/badge/version-3.0-blue.svg)](#version-history)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#installation)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

</div>

---

CommentRemover creates a cleaned copy of a project with comments stripped out. The original is **never touched** unless you explicitly pass `--in-place`.

```bash
python3 CommentRemoverV3-1.py -p ./my-project
```

Creates a timestamped copy (`my-project_Clean_2026-01-02_03-04-05`) next to the original — nothing in the source tree changes, and unsupported files are simply left as-is unless you opt in to `-d`/`--delete`.

## Why this exists

Most comment-stripping one-liners are a single regex that quietly breaks on the first raw string, heredoc, multi-line string, or nested block comment they meet. This tool takes a different approach: **155 file extensions via a shared, configurable engine**, dedicated handlers for the cases a naive regex gets wrong, an actual language tokenizer for Python, and an optional `--verify` pass that re-checks every cleaned file with the real compiler/interpreter for that language before it's written to disk. Zero required dependencies, standard library only.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [All options](#all-options)
- [Deleting non-program assets](#deleting-non-program-assets)
- [`--verify`: making sure the code still runs](#--verify-making-sure-the-code-still-runs)
- [Lines of Code (LoC)](#lines-of-code-loc)
- [HTML Report](#html-report)
- [Supported languages](#supported-languages)
- [Intentionally not supported](#intentionally-not-supported)
- [Known extension conflicts](#known-extension-conflicts)
- [How it works internally](#how-it-works-internally)
- [Important notes](#important-notes)
- [Security notice](#security-notice)
- [Known limitations](#known-limitations)
- [License](#license)

## Installation

No installation, no dependencies — a single, self-contained Python 3 script.

```bash
curl -O https://raw.githubusercontent.com/NoAuthZone/CommentRemover/main/CommentRemoverV3-1.py
python3 CommentRemoverV3-1.py --version
```

That's it. Every one of the 155 supported extensions, including Python's real tokenizer, Rust's raw-string handling, and JSP's three independent comment layers, runs on the standard library alone — nothing to `pip install`.

## Quick start

```bash
# Create a clean copy, leave the original untouched
python3 CommentRemoverV3-1.py -p ./my-project

# Re-check every file with the real compiler/interpreter for its language
python3 CommentRemoverV3-1.py -p ./my-project --verify

# Also generate a browsable HTML diff report
python3 CommentRemoverV3-1.py -p ./my-project --debug-diff

# Collapse blank lines left behind by removed comments
python3 CommentRemoverV3-1.py -p ./my-project --blank-lines squeeze

# Custom output location instead of the timestamped default
python3 CommentRemoverV3-1.py -p ./my-project -o ./my-project-clean

# Also delete non-code assets (images, archives, docs, ...) from the copy
python3 CommentRemoverV3-1.py -p ./my-project -d

# Keep only specific file types, delete everything else
python3 CommentRemoverV3-1.py -p ./my-project -d --del-exclude .py .js .ts

# Clean the original in place (DESTRUCTIVE — use with version control)
python3 CommentRemoverV3-1.py -p ./my-project --in-place
```

## All options

| Option | Description |
|---|---|
| `-p, --path DIR` | Path to the project to clean (required) |
| `-o, --output DIR` | Custom destination instead of the timestamped default name |
| `--in-place` | **Destructive:** clean directly inside `--path`, no copy is made |
| `--debug-diff` | Write a browsable HTML diff report (index + per-file diffs) |
| `--blank-lines {keep,squeeze,drop}` | How to handle blank lines left behind by comment removal |
| `--no-progress` | Disable the live per-file progress indicator (useful for CI logs) |
| `--verify` | Re-check cleaned files with the real language tool (see below) |
| `-d, --delete` | Also delete non-code assets from the copy |
| `--del-include EXT [EXT ...]` | Replace the built-in delete list entirely — delete ONLY these extensions |
| `--del-exclude EXT [EXT ...]` | Invert the logic — keep only the listed extensions, delete everything else |
| `--version` | Show the version number |

`-o/--output` and `--in-place` are mutually exclusive; `--del-include` and `--del-exclude` are mutually exclusive.

## Deleting non-program assets

Deletion is off by default — the clean copy keeps every file, whether or not CommentRemover knows how to strip comments from it. Passing `-d`/`--delete` removes non-program assets after cleaning, using one of three modes:

**Default (built-in list)** — deletes common ballast types (images, archives, docs, and similar):
```bash
python3 CommentRemoverV3-1.py -p ./my-project -d
```

**`--del-include EXT ...`** — replaces the built-in list entirely; only the listed extensions are deleted:
```bash
python3 CommentRemoverV3-1.py -p ./my-project -d --del-include .png .jpg .zip
```

**`--del-exclude EXT ...`** — inverts the built-in list ("keep-only" mode): every file whose extension is *not* listed is deleted. Extensionless files (`Dockerfile`, `LICENSE`, `Makefile`, `.gitignore`, ...) are always kept:
```bash
python3 CommentRemoverV3-1.py -p ./my-project -d --del-exclude .py .js .ts
```

`--del-include`/`--del-exclude` only take effect together with `-d`; using either without `-d` prints a warning and has no effect. `.git` directories are always skipped during deletion, regardless of mode.

## `--verify`: making sure the code still runs

```bash
python3 CommentRemoverV3-1.py -p ./my-project --verify
```

After stripping comments, each file is re-checked — when the tool is available on your system — with the **real compiler or interpreter for that language**, not another heuristic:

| Language | Check |
|---|---|
| Python | `ast.parse()` (in-process, stdlib) |
| JSON | `json.loads()` (in-process) |
| JavaScript | `node --check` |
| C / C++ | `gcc` / `g++ -fsyntax-only` |
| Bash | `bash -n` |
| Perl | `perl -c` |
| PHP | `php -l` |
| Ruby | `ruby -c` |
| Lua | `luac -p` |
| Go | `gofmt -e` |

**If the check fails, the file is left completely untouched** — nothing is ever overwritten. At the end of the run you get a summary: passed / failed / no checker installed on this system / no verifier wired up for this language.

Deliberately **not** wired up (would produce too many false failures or need project context CommentRemover doesn't have): TypeScript (`tsc` needs tsconfig context), Java (`javac` needs classpath and matching filename), Rust (`rustc` has no stable syntax-only flag), and JSP (needs a servlet container/classpath).

### The honest limit of `--verify`

`--verify` guarantees **syntax**, not **semantics**. It reliably catches "the program no longer runs." It does not catch a bug that produces syntactically valid but behaviorally different output.

**For production-critical code:** always run with `--verify` (free, no downside), add `--debug-diff` for a spot-check of the actual diff, and run your own test suite against the cleaned copy afterward.

## Lines of Code (LoC)

At the end of every run, CommentRemover prints a full before/after LoC breakdown, covering every common definition of "lines of code":

```text
Lines of code:
  Total lines (incl. blanks/comments) :  128,140 ->  128,117  (-0.0%)
  Blank lines                         :   24,668 ->   30,078  (+21.9%)
  Non-blank lines (incl. comments)    :  103,472 ->   98,039  (-5.3%)
  Comment-only lines                  :    5,433 ->        0  (-100.0%)
  Code lines (no blanks/comments)     :   98,039 ->   98,039  (0.0%)

LoC by file type (before -> after):
  Type   Code            Comment      Blank            Total
  .py    1,142 -> 922    200 -> 0     120 -> 200      1,462 -> 1,122
  .js    612 -> 501      90 -> 0      21 -> 30        723 -> 531
```

Each category is computed by comparing every file's original content against its comment-stripped content, line by line (line positions are preserved by every handler, so this comparison is exact):

- **Total lines** — every physical line in the file, including blanks and comments.
- **Blank lines** — lines that are empty or whitespace-only. This number typically *increases* after cleaning, because a line that was 100% comment becomes a blank line (use `--blank-lines squeeze`/`drop` to remove them).
- **Non-blank lines** — total minus blank; includes both code and (before cleaning) comments.
- **Comment-only lines** — lines that were entirely comment and disappear (become blank) after cleaning.
- **Code lines** — real code, excluding blanks and comment-only lines. This is the most meaningful "did the tool actually remove code" check: it should stay the same before/after, since comment stripping never removes code.

Both the overall breakdown and the per-file-type table are also printed for `--in-place` runs, and, with `--debug-diff`, appear as a card and two tables in the HTML report.

## HTML Report

Open the generated report in a browser:
```bash
xdg-open /path/to/my-project_Clean_DATE_DEBUG-FILE/index.html
```

The report includes:

- Total modified files, removed/added line counts (diff-based)
- Overall project size reduction
- Overall LoC reduction, plus a breakdown by file type
- Project directory structure with change status for files and folders
- A search field, with `Changed only`, `All files`, and `Unchanged only` filters
- Direct links to file-specific diff reports
- Original source, cleaned source, and Git-style diff views (only-changes and side-by-side context modes)

## Supported languages

**155 file extensions**, grouped by comment-syntax family:

- **Python** — runs through Python's own `tokenize` module (the same tokenizer CPython itself uses), not a heuristic. Preserves exact original formatting, handles f-strings, the walrus operator, even lexically-valid Python 2 code.
- **Rust** — a hand-written, priority-ordered regex tokenizer. Correctly distinguishes lifetimes from char literals, understands raw strings (`r"..."`, `r#"..."#`, up to `r###"..."###`) and backslash-newline string continuations.
- **HTML** — cleans embedded `<style>` blocks with real CSS rules and `<script>` blocks with real JavaScript rules (skipping non-JS types like `application/json`), not just the outer `<!-- -->` comments. Applied to Svelte templates too.
- **JSP / JSP fragments (`.jsp`, `.jspf`)** — strips all three independent comment layers a JSP file can contain: `<%-- ... --%>` JSP comments (translation-time only, may span multiple lines), `//` and `/* */` inside `<% %>` scriptlets, `<%! %>` declarations, `<%= %>` expressions and `<%@ %>` directives (reusing the Java handler, so a `%>` sitting inside a Java string never ends the tag early), and `<!-- ... -->` literal HTML comments in the template portion.
- **C family** — C, C++, C#, Go, CSS/SCSS/LESS, GLSL/HLSL, Solidity, Verilog/SystemVerilog, Move, Cairo, X10, Carbon, Ballerina, ReScript, Apex triggers
- **Nested block comments** — Swift, Kotlin, Scala, Odin, Chapel
- **Java, Groovy**
- **JavaScript/TypeScript/ActionScript** (incl. JSX/TSX)
- **Bash/Shell, Fish, Zsh** — whole-file quote and heredoc tracking (not line-by-line); correctly distinguishes the arithmetic left-shift operator (`$((n << x))`) from a heredoc
- **R** — same whole-file tracking as Bash
- **Perl** — heredoc-aware
- **MATLAB** — distinguishes the transpose operator (`A'`) from a string literal; enforces the real rule that `%{`/`%}` only start a block comment when alone on their line
- **Terraform/HCL** — heredoc-aware
- **INI** — supports both `#` and line-leading `;` comments (the traditional Windows-INI style), without touching a legitimate `;` inside a value
- Ruby, PHP, SQL, Lua, Dart, Julia, Ada, VBA/VB.NET/classic BASIC, PowerShell, Delphi/Object Pascal/Pascal, Modula-2, Fortran (free + fixed form), COBOL (free format), OCaml, Racket/Scheme/Common Lisp, Clojure, F#, Crystal, Nim, Zig, VHDL, CoffeeScript, ColdFusion (tags only), Tcl, Elm, PureScript, Idris, Agda, Handlebars, Liquid, SAS, Wolfram Language, GAMS, Smalltalk, PL/I, Forth, x86 Assembly, Logo, ABAP, Red, Io, Factor, J, APL, Sed, Stata, Vyper, Erlang
- XML/XAML/SVG, YAML, TOML, CFG/Properties, JSON (verify only), Dockerfile

For the complete, generated list:
```bash
python3 CommentRemoverV3-1.py --help
```

### Full extension table

| Language | File extension(s) |
|---|---|
| ABAP | `.abap` |
| ActionScript | `.as` |
| Ada | `.ada`, `.adb`, `.ads` |
| Agda | `.agda` |
| Apex (trigger files only) | `.trigger` |
| APL | `.apl`, `.dyalog` |
| Assembly (x86) | `.asm`, `.s` |
| AWK | `.awk` |
| Ballerina | `.bal` |
| BASIC (classic) / VBA / VB.NET | `.bas`, `.cls`, `.frm`, `.vb` |
| Bash / Shell | `.sh` |
| C | `.c`, `.h` |
| C++ | `.cpp`, `.cc`, `.hpp` |
| C# | `.cs` |
| Cairo | `.cairo` |
| Carbon | `.carbon` |
| Chapel | `.chpl` |
| Clojure | `.clj`, `.cljc`, `.cljs` |
| COBOL (free format) | `.cbl`, `.cob` |
| CoffeeScript | `.coffee` |
| ColdFusion (tags only) | `.cfm`, `.cfc` |
| Common Lisp | `.lisp`, `.lsp` |
| Crystal | `.cr` |
| CSS | `.css` |
| Dart | `.dart` |
| Delphi / Object Pascal / Pascal | `.pas`, `.dpr`, `.pp` |
| Dockerfile | `Dockerfile` (no extension) |
| Elixir | `.ex`, `.exs` |
| Elm | `.elm` |
| Erlang | `.erl`, `.hrl` |
| F# | `.fs`, `.fsx`, `.fsi` |
| Factor | `.factor` |
| Fish (shell) | `.fish` |
| Forth | `.fth` |
| Fortran (free format) | `.f90`, `.f95`, `.f03`, `.f08` |
| Fortran (fixed format) | `.f`, `.for` |
| GAMS | `.gms` |
| GLSL / HLSL (shaders) | `.glsl`, `.hlsl`, `.vert`, `.frag`, `.geom`, `.comp` |
| Go | `.go` |
| Groovy | `.groovy` |
| Handlebars | `.hbs`, `.handlebars` |
| HTML | `.html`, `.htm` |
| Idris | `.idr` |
| INI | `.ini` |
| Io | `.io` |
| J | `.ijs` |
| Java | `.java` |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.mts`, `.cts` |
| JSP / JSP fragments | `.jsp`, `.jspf` |
| JSX / TSX | `.jsx`, `.tsx` |
| Julia | `.jl` |
| Kotlin | `.kt`, `.kts` |
| LESS | `.less` |
| Liquid | `.liquid` |
| Logo | `.logo` |
| Lua | `.lua` |
| MATLAB | `.m` |
| Modula-2 | `.mod` |
| Mojo | `.mojo` |
| Move | `.move` |
| Nim | `.nim` |
| Objective-C++ | `.mm` |
| OCaml | `.ml`, `.mli` |
| Odin | `.odin` |
| Perl | `.pl`, `.pm` |
| PHP | `.php` |
| PL/I | `.pl1`, `.pli` |
| PowerShell | `.ps1`, `.psm1`, `.psd1` |
| Properties / CFG / CONF | `.cfg`, `.conf`, `.properties` |
| PureScript | `.purs` |
| Python | `.py` |
| R | `.r` |
| Racket | `.rkt` |
| Red | `.red` |
| ReScript | `.res` |
| Ruby | `.rb` |
| Rust | `.rs` |
| SAS | `.sas` |
| Scala | `.scala` |
| Scheme | `.scm`, `.ss` |
| SCSS | `.scss` |
| Sed | `.sed` |
| Smalltalk | `.st` |
| Solidity | `.sol` |
| SQL | `.sql` |
| Standard ML | `.sml`, `.sig` |
| Stata | `.do`, `.ado` |
| Svelte (template portion only) | `.svelte` |
| SVG | `.svg` |
| Swift | `.swift` |
| Tcl | `.tcl` |
| Terraform / HCL | `.tf` |
| TOML | `.toml` |
| TypeScript | `.ts` |
| Verilog / SystemVerilog | `.v`, `.sv` |
| VHDL | `.vhd`, `.vhdl` |
| Vyper | `.vy` |
| Wolfram Language | `.wl` |
| X10 | `.x10` |
| XAML | `.xaml` |
| XML | `.xml` |
| YAML | `.yaml`, `.yml` |
| Zig | `.zig` |
| Zsh (shell) | `.zsh` |

**Total: 155 file extensions.**

## Intentionally not supported

| Language / case | Reason |
|---|---|
| LabVIEW, Ladder Logic | Graphical/binary formats — no text comment syntax to parse |
| K/Q (kdb+) | `/` means division *or* comment-start depending on context — too ambiguous to strip safely without risking silent data loss |
| Fixed-format COBOL, RPG, Algol, Simula | Column/dialect-specific rules too inconsistent to encode with confidence |
| SAS's `* ... ;` comment form | Only valid at statement start, otherwise multiplication — only the safe `/* */` form is stripped |
| Prolog (`.pl`), Coq (`.v`) | Extensions already claimed by the far more common Perl and Verilog |

## Known extension conflicts

Some extensions are shared by more than one language. Decision and rationale:

| Extension | Conflict | Decision |
|---|---|---|
| `.m` | MATLAB vs. Objective-C | → MATLAB (more common); Objective-C implementation files aren't cleaned (`.h`/`.mm` still work) |
| `.pl` | Perl vs. Prolog | → Perl (far more common) |
| `.v` | Verilog vs. Coq | → Verilog (far more common) |
| `.fs` | F# vs. Forth | → F#; Forth uses `.fth` instead |
| `.cls` | VBA vs. Apex | → VBA (established first); Apex triggers use `.trigger` instead |
| `.bas` | VBA vs. classic BASIC | Not a real conflict — both share the same comment syntax (`'` and `Rem`) |

## How it works internally

Most of the 155 extensions go through a **configurable generic engine** (comment tokens, block delimiters, and string-escaping rules as parameters) instead of a bespoke parser per language. Languages with real edge cases get a dedicated handler:

- **Python** — the stdlib `tokenize` module
- **Rust** — a small hand-written, priority-ordered regex tokenizer (no external parsing library needed)
- **Bash, R, Terraform, Perl** — dedicated handlers with whole-file state tracking (heredocs, multi-line strings, arithmetic-context awareness for Bash)
- **MATLAB** — a dedicated, line-aware handler for the transpose-vs-string ambiguity and the alone-on-its-line block-comment rule
- **HTML** — a dedicated handler that hands `<style>`/`<script>` contents to the real CSS/JS handlers before the outer `<!-- -->` pass
- **JSP** — a dedicated handler that walks `<%-- --%>`, `<% %>`-family tags (delegating their contents to the Java handler), and `<!-- -->` independently

## Important notes

- By default the original project is not modified; every operation runs on a copy (timestamped, or custom-named via `-o`/`--output`).
- `--in-place` is destructive: it skips the copy step and modifies the source directory directly. Combined with `-d`, matching files are permanently deleted from it. The script prints an explicit warning when `--in-place` is used, and a second one if combined with `-d`. Use it only on projects already under version control.
- Symlinks are skipped during cleaning, so a symlink pointing outside the copy can never be overwritten — this protection also applies in `--in-place` mode.
- Files with no comment handler are left untouched (copied/left as-is); they are only removed if `-d` is used and they match the active delete list. Extensionless files (`Dockerfile`, `LICENSE`, `.gitignore`, ...) are always kept in `--del-exclude` mode.
- Comment removal is syntax-aware but does not replace a complete language parser.
- Always review the generated diff before distributing or deploying the cleaned copy.

## Security notice

HTML debug reports contain the complete original and cleaned contents of changed files. If source files contain passwords, API keys, access tokens, private URLs, personal data, or other secrets, those values may also appear in the reports.

Before publishing or sharing a `_DEBUG-FILE` directory:

- Review all generated reports
- Scan the output for secrets
- Do not commit sensitive reports to a public repository
- Add generated output directories to `.gitignore`

Example:

```gitignore
*_Clean_*/
*_DEBUG-FILE/
```

Configuration files such as YAML, TOML, INI, Terraform, and properties files may contain credentials even when they are treated as source files.

## Known limitations

- `--verify` checks syntax, not semantics (see above)
- ColdFusion, non-HTML Svelte edge cases: only the tag/template and `<style>`/`<script>` portions are processed the way HTML does; not every embedded-language combination is covered
- Assembly, Forth: string literals aren't specially protected (both languages have unusual/rare string constructs)
- SAS: the statement-bound `*` comment form is intentionally not removed, for safety
- INI: only a `;` that is the first non-whitespace character on its line is treated as a comment — a trailing inline `; comment` is left alone, since a literal `;` inside a value (e.g. a PATH-style list) can't be safely distinguished from one
- JavaScript regular expressions and template strings, C++ raw strings, mixed PHP/HTML documents, and special SQL quoting rules may need manual review

Use the HTML diff reports to verify every change.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Author

**NoAuthZone**
- GitHub: https://github.com/NoAuthZone/CommentRemover

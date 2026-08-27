<div align="center">

# CommentRemover

**Strip code comments from an entire project, across 153 file types — without touching a single line of real code.**

[![Version](https://img.shields.io/badge/version-3.0-blue.svg)](#version-history)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#installation)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

</div>

---

CommentRemover creates a cleaned copy of a project with comments stripped out. The original is **never touched** unless you explicitly pass `--in-place`.

```bash
python3 CommentRemover.py -p ./my-project
```

Creates a timestamped copy (`my-project_Clean_2026-01-02_03-04-05`) next to the original — nothing in the source tree changes.

## Why this exists

Most comment-stripping one-liners are a single regex that quietly breaks on the first raw string, heredoc, multi-line string, or nested block comment they meet. This tool takes a different approach: **153 languages via a shared, configurable engine**, dedicated handlers for the cases a naive regex gets wrong, an actual language tokenizer for Python, and an optional `--verify` pass that re-checks every cleaned file with the real compiler/interpreter for that language before it's written to disk. Zero required dependencies, standard library only.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [All options](#all-options)
- [`--verify`: making sure the code still runs](#--verify-making-sure-the-code-still-runs)
- [Supported languages](#supported-languages)
- [Intentionally not supported](#intentionally-not-supported)
- [Known extension conflicts](#known-extension-conflicts)
- [How it works internally](#how-it-works-internally)
- [Known limitations](#known-limitations)
- [Version history](#version-history)
- [Contributing](#contributing)

## Installation

No installation, no dependencies — a single, self-contained Python 3 script.

```bash
curl -O https://raw.githubusercontent.com/NoAuthZone/CommentRemover/main/CommentRemover.py
python3 CommentRemover.py --version
```

That's it. Every one of the 153 supported languages, including Python's real tokenizer and Rust's raw-string handling, runs on the standard library alone — nothing to `pip install`.

## Quick start

```bash
# Create a clean copy, leave the original untouched
python3 CommentRemover.py -p ./my-project

# Re-check every file with the real compiler/interpreter for its language
python3 CommentRemover.py -p ./my-project --verify

# Also generate a browsable HTML diff report
python3 CommentRemover.py -p ./my-project --debug-diff

# Collapse blank lines left behind by removed comments
python3 CommentRemover.py -p ./my-project --blank-lines squeeze

# Custom output location instead of the timestamped default
python3 CommentRemover.py -p ./my-project -o ./my-project-clean

# Also delete non-code assets (images, archives, docs, ...) from the copy
python3 CommentRemover.py -p ./my-project -d

# Keep only specific file types, delete everything else
python3 CommentRemover.py -p ./my-project -d --del-exclude .py .js .ts

# Clean the original in place (DESTRUCTIVE — use with version control)
python3 CommentRemover.py -p ./my-project --in-place
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
| `--del-include EXT [EXT ...]` | Replace the built-in delete list entirely |
| `--del-exclude EXT [EXT ...]` | Invert the logic: keep only the listed extensions |
| `--version` | Show the version number |

## `--verify`: making sure the code still runs

```bash
python3 CommentRemover.py -p ./my-project --verify
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

Deliberately **not** wired up (would produce too many false failures):
- **TypeScript** — `tsc` needs project/tsconfig context for a reliable single-file check
- **Java** — `javac` needs the filename to match the public class name and usually a classpath
- **Rust** — `rustc` has no stable syntax-only flag; a real check needs crate dependencies most single files don't carry

### The honest limit of `--verify`

`--verify` guarantees **syntax**, not **semantics**. It reliably catches "the program no longer runs." It does **not** catch a bug that produces syntactically valid but behaviorally different output — several of the bugs in the [version history](#version-history) below were exactly that: a Perl heredoc, a multi-line Bash string, or a mid-line MATLAB `%{` whose surrounding content was misread, while the result stayed perfectly valid syntax.

**For production-critical code:**
1. Always run with `--verify` — it's free, no downside
2. Add `--debug-diff` for a spot-check of the actual diff
3. Run your own test suite against the cleaned copy afterward — that's the only step that also catches subtler cases like the ones above

## Supported languages

**153 file extensions**, grouped by comment-syntax family:

- **Python** — runs through Python's own `tokenize` module (the same tokenizer CPython itself uses), not a heuristic. Preserves exact original formatting, handles f-strings, the walrus operator, even lexically-valid Python 2 code.
- **Rust** — a hand-written, priority-ordered regex tokenizer. Correctly distinguishes lifetimes from char literals, understands raw strings (`r"..."`, `r#"..."#`, up to `r###"..."###`) and backslash-newline string continuations.
- **HTML** — cleans embedded `<style>` blocks with real CSS rules and `<script>` blocks with real JavaScript rules (skipping non-JS types like `application/json`), not just the outer `<!-- -->` comments. Applied to Svelte templates too.
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
python3 CommentRemover.py --help
```

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

Most of the 153 languages go through a **configurable generic engine** (comment tokens, block delimiters, and string-escaping rules as parameters) instead of a bespoke parser per language. Languages with real edge cases get a dedicated handler:

- **Python** — the stdlib `tokenize` module
- **Rust** — a small hand-written, priority-ordered regex tokenizer (no external parsing library needed)
- **Bash, R, Terraform, Perl** — dedicated handlers with whole-file state tracking (heredocs, multi-line strings, arithmetic-context awareness for Bash)
- **MATLAB** — a dedicated, line-aware handler for the transpose-vs-string ambiguity and the alone-on-its-line block-comment rule
- **HTML** — a dedicated handler that hands `<style>`/`<script>` contents to the real CSS/JS handlers before the outer `<!-- -->` pass

## Known limitations

- `--verify` checks syntax, not semantics (see above)
- ColdFusion, non-HTML Svelte edge cases: only the tag/template and `<style>`/`<script>` portions are processed the way HTML does; not every embedded-language combination is covered
- Assembly, Forth: string literals aren't specially protected (both languages have unusual/rare string constructs)
- SAS: the statement-bound `*` comment form is intentionally not removed, for safety
- INI: only a `;` that is the first non-whitespace character on its line is treated as a comment — a trailing inline `; comment` is left alone, since a literal `;` inside a value (e.g. a PATH-style list) can't be safely distinguished from one



# CommentRemover — Supported Languages

Complete list of all 153 supported file extensions, grouped by language, extracted directly from the tool's `HANDLERS` table.

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

**Total: 153 file extensions.**

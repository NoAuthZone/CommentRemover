# CommentRemover

CommentRemover creates a clean, code-only copy of a software project by removing comments while preserving line positions. Optional HTML reports provide a searchable project tree, change filters, full source views, and Git-style side-by-side diffs.

By default, the original project is never modified - every operation runs on a timestamped copy, and symlinks that point outside the project are skipped rather than followed. An explicit `--in-place` flag is available for cases where you want to skip the copy and clean files directly.

## Features

**Copying & Output**
* Creates a timestamped copy of the source project by default, or a custom-named copy via `-o`/`--output`
* Optional `--in-place` mode to skip the copy entirely and clean files directly inside the source project (opt-in, prints a warning)

**Cleaning / Comment Removal**
* Removes comments from supported source and configuration files
* Correctly handles multi-line strings (e.g. Python docstrings, TOML multi-line strings) so a `#` inside them is never mistaken for a comment
* Preserves comment line breaks to keep line numbers comparable
  * Optionally collapses or drops blank lines left behind by removed comments (`--blank-lines`)
* Optionally deletes non-program assets from the copy, with full control over which extensions (`-d`, `--del-include`, `--del-exclude`)

**Safety**
* Skips symlinks during cleaning so files outside the copy can never be overwritten

**Progress & Reporting**
* Shows a live per-file progress indicator, with a project size reduction summary at the end
* Generates reports in a separate `_DEBUG-FILE` directory

**Diff View & Navigation**
* Shows original and cleaned files in a side-by-side Git-style diff
* Provides `All files`, `Changed only`, and `Unchanged only` filters
* Includes file and directory search

**Statistics**
* Displays changed file counts, added/removed line totals, and overall size reduction

## Output

Running CommentRemover with HTML reports creates two separate directories:

```text
my-project_Clean_2026-07-20_21-49-52/
my-project_Clean_2026-07-20_21-49-52_DEBUG-FILE/
```

The clean directory is a full copy of the project with comments stripped from supported files. Files with no comment handler (e.g. `.json`, `.lock`) are copied through unchanged unless removed via `-d`.

The separate debug directory contains the HTML reports:

```text
my-project_Clean_..._DEBUG-FILE/
```

## Requirements

- Python 3
- No external Python packages are required

## Installation

Clone the repository:

```bash
git clone https://github.com/NoAuthZone/CommentRemover.git
cd CommentRemover
```

Make the script executable on Linux:

```bash
chmod +x CommentRemoverV2_1.py
```

## Usage

Create a clean, code-only copy:
```bash
python3 CommentRemoverV2_1.py --path /path/to/project
```

Create a clean copy and a separate HTML diff report:
```bash
python3 CommentRemoverV2_1.py --path /path/to/project --debug-diff
```

Short path option:
```bash
python3 CommentRemoverV2_1.py -p /path/to/project --debug-diff
```

Collapse blank lines left behind by removed comments:
```bash
python3 CommentRemoverV2_1.py -p /path/to/project --blank-lines squeeze
# or drop them entirely
python3 CommentRemoverV2_1.py -p /path/to/project --blank-lines drop
```

Disable the live progress indicator (useful for CI logs or piped output):
```bash
python3 CommentRemoverV2_1.py -p /path/to/project --no-progress
```

Use a custom name/location for the copy instead of the timestamped default:
```bash
python3 CommentRemoverV2_1.py -p /path/to/project -o /path/to/project-clean
```

Skip the copy entirely and clean the files directly in place (destructive - see [Important Notes](#important-notes)):
```bash
python3 CommentRemoverV2_1.py -p /path/to/project --in-place
```

Show help:
```bash
python3 CommentRemoverV2_1.py --help
```

Show the version:
```bash
python3 CommentRemoverV2_1.py --version
```

## Deleting Non-Program Assets

Deletion is off by default. Passing `-d`/`--delete` removes non-program assets from the copy after cleaning, using one of three modes:

**Default (built-in list)** - deletes the built-in ballast types (images, archives, docs, and similar):
```bash
python3 CommentRemoverV2_1.py -p /path/to/project -d
```

**`--del-include EXT ...`** - replaces the built-in list entirely; only the listed extensions are deleted:
```bash
python3 CommentRemoverV2_1.py -p /path/to/project -d --del-include .png .jpg .zip
```

**`--del-exclude EXT ...`** - inverts the built-in list ("keep-only" mode): every file whose extension is *not* listed is deleted. Extensionless files (`Dockerfile`, `LICENSE`, `Makefile`, `.gitignore`, ...) are always kept:
```bash
python3 CommentRemoverV2_1.py -p /path/to/project -d --del-exclude .py .js .ts
```

`--del-include` and `--del-exclude` are mutually exclusive and only take effect together with `-d`; using either without `-d` prints a warning and has no effect.

`.git` directories are always skipped during deletion, regardless of mode.

## HTML Report

Open the generated report in a browser:
```bash
xdg-open /path/to/my-project_Clean_DATE_DEBUG-FILE/index.html
```

The report includes:

- Total modified files
- Removed and added line counts
- Overall project size reduction
- Project directory structure
- Change status for files and folders
- A search field
- `Changed only` filter enabled by default
- `All files` and `Unchanged only` filters
- Direct links to file-specific diff reports
- Original source, cleaned source, and Git-style diff views

## Supported Comment Styles

### Hash comments

```text
# Comment
```

Used for Python, YAML, Shell, TOML, Ruby, Terraform, INI/CFG/Properties, and similar formats. Multi-line strings (Python docstrings, TOML multi-line strings) are tracked across lines, so a `#` inside them is preserved rather than treated as a comment.

### C-style comments

```text
// Line comment
/* Block comment */
```

Used for Java, C, C++, C#, JavaScript, TypeScript (incl. JSX/TSX), Go, Swift, Kotlin, CSS, SCSS, LESS, Rust, and similar languages.

### SQL comments

```text
-- Line comment
# Alternative line comment
/* Block comment */
```

### PHP comments

```php
// Line comment
# Alternative PHP comment
/* Block comment */
```

### HTML and XML comments

```html
<!-- Comment -->
```

### Lua comments

```lua
-- Line comment
--[[ Block comment ]]
```

## Supported Files

Common supported extensions include:

```text
.py .sh .toml .rb .tf
.yml .yaml
.ini .cfg .conf .properties
.cs .c .cpp .cc .h .hpp .go .swift .kt .kts .css .scss .less .rs
.java
.js .ts .mjs .cjs .mts .cts .jsx .tsx
.html .htm .php .sql .xml .xaml .svg .lua
```

Files named `Dockerfile` are also supported.

## Important Notes

- By default the original project is not modified; every operation runs on a copy (timestamped, or custom-named via `-o`/`--output`).
- `--in-place` is destructive: it skips the copy step and modifies the source directory directly. Combined with `-d`, matching files are permanently deleted from it. The script prints an explicit warning when `--in-place` is used, and a second one if combined with `-d`. Use it only on projects already under version control.
- Symlinks are skipped during cleaning, so a symlink pointing outside the copy can never be overwritten - this protection also applies in `--in-place` mode.
- Files with no comment handler are left untouched (copied/left as-is); they are only removed if `-d` is used and they match the active delete list.
- Comment removal is syntax-aware but does not replace a complete language parser.
- Always review the generated diff before distributing or deploying the cleaned copy.

## Security Notice

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

## Limitations

CommentRemover uses lightweight syntax handling rather than full parsers. Complex constructs may require manual review, including:

- JavaScript regular expressions and template strings
- C++ raw strings
- Mixed PHP and HTML documents
- Special SQL quoting rules
- Language-specific nested syntax
- Heredocs (e.g. Ruby `<<~TEXT`, Bash `<<EOF`, Terraform `<<EOT`) are not multi-line-string-aware the way Python/TOML triple-quoted strings are

Use the HTML diff reports to verify every change.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Author

**NoAuthZone**
- GitHub: https://github.com/NoAuthZone/CommentRemover

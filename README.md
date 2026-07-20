# CommentRemover

CommentRemover creates a clean, code-only copy of a software project by removing comments while preserving line positions. Optional HTML reports provide a searchable project tree, change filters, full source views, and Git-style side-by-side diffs.

The original project is never modified.

## Features

- Creates a timestamped copy of the source project
- Removes comments from supported source and configuration files
- Preserves comment line breaks to keep line numbers comparable
- Keeps only supported code and configuration files in the clean copy
- Removes empty directories after cleanup
- Generates reports in a separate `_DEBUG-FILE` directory
- Shows original and cleaned files in a side-by-side Git-style diff
- Provides `All files`, `Changed only`, and `Unchanged only` filters
- Includes file and directory search
- Displays changed file counts and added/removed line totals
- Preserves the original project

## Output

Running CommentRemover with HTML reports creates two separate directories:

```text
my-project_Clean_2026-07-20_21-49-52/
my-project_Clean_2026-07-20_21-49-52_DEBUG-FILE/
```

The clean directory contains supported source and configuration files only:

```text
my-project_Clean_.../
```

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
chmod +x CommentRemover.py
```

## Usage

Create a clean, code-only copy:
```bash
python3 CommentRemover.py --path /path/to/project
```

Create a clean copy and separate HTML reports:
```bash
python3 CommentRemover.py --path /path/to/project --debug-diff
```

Short path option:
```bash
python3 CommentRemover.py -p /path/to/project --debug-diff
```

Show help:
```bash
python3 CommentRemover.py --help
```

Show the version:
```bash
python3 CommentRemover.py --version
```

## HTML Report

Open the generated report in a browser:
```bash
xdg-open /path/to/my-project_Clean_DATE_DEBUG-FILE/index.html
```

The report includes:

- Total modified files
- Removed and added line counts
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

Used for Python, YAML, Shell, TOML, INI, configuration files, and similar formats.

### C-style comments

```text
// Line comment
/* Block comment */
```

Used for Java, C, C++, C#, JavaScript, TypeScript, Go, Swift, Kotlin, CSS, Rust, and similar languages.

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
.py .yml .yaml .sh .ini .cfg .conf .properties .toml .rb .tf
.java .cs .c .cpp .cc .h .hpp .js .jsx .ts .tsx
.go .swift .kt .kts .css .scss .less .rs
.html .htm .php .sql .xml .xaml .svg .lua
```

Files named `Dockerfile` are also supported.

## Important Notes

- The original project is not modified.
- The clean copy contains only supported source and configuration files.
- Unsupported files are deleted from the clean copy.
- Empty directories are removed from the clean copy.
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

Use the HTML diff reports to verify every change.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Author

**NoAuthZone**
- GitHub: https://github.com/NoAuthZone/CommentRemover

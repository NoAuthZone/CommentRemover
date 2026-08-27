#!/usr/bin/env python3
"""
CommentRemover - Create a cleaned project copy (comments stripped) and
optional scalable HTML diff reports, across 150+ file types.
"""

import argparse
import ast
import functools
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tokenize

from datetime import datetime

PROGRAM_NAME = "CommentRemover"
PROGRAM_VERSION = "3.0"
PROGRAM_AUTHOR = "NoAuthZone"
PROGRAM_GITHUB = "https://github.com/NoAuthZone/CommentRemover"
DIFF_CONTEXT_LINES = 5
MAX_FULL_SOURCE_BYTES = 1_000_000

changes = []
verify_stats = {"passed": 0, "failed": 0, "unavailable": set(), "no_verifier": set()}
debug_reports = []
deleted_files = []

LOC_CATEGORIES = ("total", "blank", "comment", "code")


def new_loc_bucket():
    return {"total": 0, "blank": 0, "comment": 0, "code": 0}


loc_stats = {"before": new_loc_bucket(), "after": new_loc_bucket()}
loc_by_extension = {}


def console_banner():
    return (
        "-------------------------------------------------------------\n"
        f"                     {PROGRAM_NAME}\n"
        "-------------------------------------------------------------\n"
        f" Version   : {PROGRAM_VERSION}\n"
        f" Author    : {PROGRAM_AUTHOR}\n"
        f" GitHub    : {PROGRAM_GITHUB}\n"
        "-------------------------------------------------------------"
    )


def restore_eof(original, cleaned):
    if original.endswith("\n") and not cleaned.endswith("\n"):
        return cleaned + "\n"
    if not original.endswith("\n") and cleaned.endswith("\n"):
        return cleaned.rstrip("\r\n")
    return cleaned


def preserve_newlines(match):
    return "".join(c for c in match.group(0) if c in "\r\n")


# ---------------------------------------------------------------------------
# Hash, YAML and configuration formats
# ---------------------------------------------------------------------------

TRIPLE_QUOTES = ('"""', "'''")


def scan_hash_line(line, triple=None, preserve_hex_colors=False):
    """Strip a '#' comment from a single line.

    ``triple`` carries a still-open triple-quote delimiter ('\"\"\"' or
    \"'''\") from the previous line, so multi-line strings (Python
    docstrings, TOML multi-line strings, ...) are no longer mistaken for
    comment territory. Returns (cleaned_line, still_open_triple_or_None).
    """
    output, quote, escaped, index = [], None, False, 0
    length = len(line)
    while index < length:
        char = line[index]
        if triple:
            if line.startswith(triple, index):
                output.append(triple); index += len(triple); triple = None; continue
            output.append(char); index += 1; continue
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if char == "\\" and quote is not None:
            output.append(char); escaped = True; index += 1; continue
        if quote is None and line[index:index + 3] in TRIPLE_QUOTES:
            triple = line[index:index + 3]
            output.append(triple); index += 3; continue
        if char in ('"', "'"):
            quote = char if quote is None else (None if quote == char else quote)
            output.append(char); index += 1; continue
        if char == "#" and quote is None:
            if preserve_hex_colors:
                match = re.match(r"#[0-9A-Fa-f]{3,8}(?![0-9A-Fa-f])", line[index:])
                if match and line[:index].rstrip().endswith(("=", ":", "(", ",")):
                    output.append(match.group(0)); index += len(match.group(0)); continue
            break
        output.append(char); index += 1
    text = "".join(output)
    # Only trim trailing whitespace when we are *not* sitting inside an
    # still-open multi-line string - otherwise we would silently eat
    # trailing spaces that are part of the string's content.
    return (text if triple else text.rstrip()), triple


def remove_hash_comments(text):
    lines, triple = [], None
    for number, line in enumerate(text.splitlines()):
        if number == 0 and triple is None and line.startswith("#!"):
            lines.append(line); continue
        cleaned, triple = scan_hash_line(line, triple)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))

def remove_python_comments_tokenize(text):
    """Uses Python's own stdlib tokenizer - the same one CPython itself uses
    - instead of a hand-rolled scanner. Since tokenize works purely lexically
    (it does not need a valid AST/grammar), it also handles legacy Python 2
    syntax and other lexically-valid-but-not-parseable code just fine.
    Returns None if the text can't even be tokenized (caller should fall
    back to remove_hash_comments rather than risk corrupting the file)."""
    lines = text.splitlines(keepends=True)
    result, prev_end_line, prev_end_col = [], 1, 0
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, UnicodeDecodeError):
        return None
    for tok_type, tok_string, (start_line, start_col), (end_line, end_col), _ in tokens:
        # Copy the exact gap (whitespace/indentation) between the previous
        # token's end and this token's start straight from the source, so
        # formatting is preserved byte-for-byte outside of stripped comments.
        if start_line == prev_end_line:
            gap = lines[start_line - 1][prev_end_col:start_col] if start_line - 1 < len(lines) else ""
        else:
            parts = []
            if prev_end_line - 1 < len(lines): parts.append(lines[prev_end_line - 1][prev_end_col:])
            for line_no in range(prev_end_line + 1, start_line):
                if line_no - 1 < len(lines): parts.append(lines[line_no - 1])
            if start_line - 1 < len(lines): parts.append(lines[start_line - 1][:start_col])
            gap = "".join(parts)
        if tok_type == tokenize.COMMENT:
            if start_line == 1 and tok_string.startswith("#!"):
                result.append(gap); result.append(tok_string)  # preserve shebang, like remove_hash_comments does
            prev_end_line, prev_end_col = end_line, end_col
            continue
        result.append(gap); result.append(tok_string)
        prev_end_line, prev_end_col = end_line, end_col
    return "".join(result)

def remove_python_comments(text):
    tokenized = remove_python_comments_tokenize(text)
    return tokenized if tokenized is not None else remove_hash_comments(text)

def remove_ruby_comments(text):
    """Like remove_hash_comments, but additionally strips =begin/=end block
    comments. Per Ruby syntax, both markers must sit at column 0 of their
    own line, so no quote/heredoc tracking is needed for the block itself."""
    lines, triple, in_block = [], None, False
    for number, line in enumerate(text.splitlines()):
        if in_block:
            lines.append("")
            if line.startswith("=end"): in_block = False
            continue
        if line.startswith("=begin"):
            in_block = True; lines.append(""); continue
        if number == 0 and triple is None and line.startswith("#!"):
            lines.append(line); continue
        cleaned, triple = scan_hash_line(line, triple)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))


def remove_config_hash_comments(text):
    lines, triple = [], None
    for line in text.splitlines():
        cleaned, triple = scan_hash_line(line, triple, preserve_hex_colors=True)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))

def remove_ini_comments(text):
    """.ini traditionally uses ';' for comments (the Windows-INI convention,
    also supported by Python's own configparser) in addition to '#'. Unlike
    '#', ';' is only stripped when it's the first non-whitespace character
    of the line - a value can legitimately contain a literal ';' elsewhere
    (e.g. a PATH-style list: path=/usr/bin;/usr/local/bin), and stripping
    that would corrupt real data, not just remove a comment."""
    without_semicolon_lines = remove_line_start_comments(text, (";",))
    lines, triple = [], None
    for line in without_semicolon_lines.splitlines():
        cleaned, triple = scan_hash_line(line, triple, preserve_hex_colors=True)
        lines.append(cleaned)
    return restore_eof(text, "\n".join(lines))


def remove_julia_comments(text):
    """Julia: '#' line comments, nestable '#= ... =#' block comments, and
    triple-quoted \"\"\" docstrings that must not be scanned for comments."""
    output, index, length = [], 0, len(text)
    quote, escaped, depth = None, False, 0
    while index < length:
        char = text[index]
        if depth > 0:
            if text.startswith("#=", index): depth += 1; index += 2; continue
            if text.startswith("=#", index): depth -= 1; index += 2; continue
            if char in "\r\n": output.append(char)
            index += 1; continue
        if quote == '"""':
            if text.startswith('"""', index):
                output.append('"""'); index += 3; quote = None; continue
            if escaped: output.append(char); escaped = False; index += 1; continue
            if char == "\\": output.append(char); escaped = True; index += 1; continue
            output.append(char); index += 1; continue
        if quote:
            output.append(char)
            if escaped: escaped = False; index += 1; continue
            if char == "\\" and quote != "'": escaped = True; index += 1; continue
            if char == quote: quote = None
            index += 1; continue
        if text.startswith('"""', index):
            quote = '"""'; output.append('"""'); index += 3; continue
        if char in ('"', "'"):
            quote = char; output.append(char); index += 1; continue
        if text.startswith("#=", index):
            depth = 1; index += 2; continue
        if char == "#":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))

def remove_ada_comments(text):
    """Ada: only '--' line comments, no block comments. Ada strings use a
    doubled quote ("") as the escape for a literal quote, not a backslash."""
    output, index, length, quote = [], 0, len(text), False
    while index < length:
        char = text[index]
        if quote:
            output.append(char)
            if char == '"':
                if index + 1 < length and text[index + 1] == '"':
                    output.append('"'); index += 2; continue
                quote = False
            index += 1; continue
        if char == '"':
            quote = True; output.append(char); index += 1; continue
        if text.startswith("--", index):
            while index < length and text[index] not in "\r\n": index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))

VBA_REM_RE = re.compile(r"(?i)^rem(\s|$)")

def remove_vba_comments(text):
    """VBA: comments start with an apostrophe, or the 'Rem' statement at the
    start of a line (case-insensitive). Strings use doubled "" as escape,
    like Ada - no backslash escaping."""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if VBA_REM_RE.match(stripped):
            lines.append(line[:len(line) - len(stripped)].rstrip()); continue
        output, quote, index, length = [], False, 0, len(line)
        while index < length:
            char = line[index]
            if quote:
                output.append(char)
                if char == '"':
                    if index + 1 < length and line[index + 1] == '"':
                        output.append('"'); index += 2; continue
                    quote = False
                index += 1; continue
            if char == '"':
                quote = True; output.append(char); index += 1; continue
            if char == "'":
                break
            output.append(char); index += 1
        lines.append("".join(output).rstrip())
    return restore_eof(text, "\n".join(lines))

def remove_yaml_comments(text):
    lines = []
    for line in text.splitlines():
        output, quote, escaped, index = [], None, False, 0
        while index < len(line):
            char = line[index]
            if escaped:
                output.append(char); escaped = False; index += 1; continue
            if quote:
                output.append(char)
                if quote == '"' and char == "\\": escaped = True
                elif char == quote:
                    if quote == "'" and index + 1 < len(line) and line[index + 1] == "'":
                        output.append("'"); index += 2; continue
                    quote = None
                index += 1; continue
            if char in ('"', "'"):
                quote = char; output.append(char); index += 1; continue
            if char != "#":
                output.append(char); index += 1; continue
            if index > 0 and not line[index - 1].isspace():
                output.append(char); index += 1; continue
            prefix, suffix = line[:index].rstrip(), line[index:]
            if re.fullmatch(r"#[^\s]+", suffix) and prefix.endswith((":", "=", "-")):
                output.append(suffix); index = len(line); continue
            break
        lines.append("".join(output).rstrip())
    return restore_eof(text, "\n".join(lines))


# ---------------------------------------------------------------------------
# C-like languages and Java
# ---------------------------------------------------------------------------


def remove_c_comments(text):
    output, index, quote, escaped = [], 0, None, False
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if quote:
            output.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            index += 1; continue
        if char in ('"', "'", "`"):
            quote = char; output.append(char); index += 1; continue
        if pair == "//":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_c_comments_nestable(text):
    """Like remove_c_comments, but block comments '/* */' may nest - required
    for Swift, Kotlin, Odin and Chapel, which explicitly allow nested block
    comments (unlike C/C++/C#/Go, where the first '*/' always closes it)."""
    output, index, length, quote, escaped, depth = [], 0, len(text), None, False, 0
    while index < length:
        char, pair = text[index], text[index:index + 2]
        if depth > 0:
            if pair == "/*": depth += 1; index += 2; continue
            if pair == "*/": depth -= 1; index += 2; continue
            if char in "\r\n": output.append(char)
            index += 1; continue
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if quote:
            output.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            index += 1; continue
        if char in ('"', "'", "`"):
            quote = char; output.append(char); index += 1; continue
        if pair == "//":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            depth = 1; index += 2; continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))

_RUST_TOKENS = (
    # Ordered by priority, exactly mirroring the terminal priorities of the
    # small Lark grammar this replaces (all these were priority 5, LIFETIME
    # was priority 4 so CHAR gets first refusal at any "'"): try each regex
    # at the current position in this order, first match wins, no lark
    # dependency needed since the grammar was simple enough to hand-port.
    ("LINE_COMMENT", re.compile(r"//[^\n]*")),
    ("BLOCK_OPEN",   re.compile(r"/\*")),
    ("BLOCK_CLOSE",  re.compile(r"\*/")),
    ("CHAR",         re.compile(r"'(\\.|[^'\\\n])'")),
    ("STRING",       re.compile(r'"(\\[\s\S]|[^"\\])*"')),
    ("RAW3",         re.compile(r'r###"(?:[^"]|"(?!###))*"###')),
    ("RAW2",         re.compile(r'r##"(?:[^"]|"(?!##))*"##')),
    ("RAW1",         re.compile(r'r#"(?:[^"]|"(?!#))*"#')),
    ("RAW0",         re.compile(r'r"[^"]*"')),
    ("LIFETIME",     re.compile(r"'[a-zA-Z_][a-zA-Z0-9_]*")),
)

def remove_rust_comments(text):
    """Priority-ordered regex tokenizer for Rust comments/strings/chars.
    Correctly distinguishes a lifetime ('a, 'static - a single UNPAIRED
    quote) from a char literal ('x', '\\n') by trying CHAR before LIFETIME
    at every "'" and taking whichever actually matches; understands raw
    strings (r"...", r#"..."#, up to r###"..."###) and backslash-newline
    string continuations; nested block comments via a depth counter."""
    output, index, length, depth = [], 0, len(text), 0
    while index < length:
        if depth > 0:
            if text.startswith("/*", index): depth += 1; index += 2; continue
            if text.startswith("*/", index): depth -= 1; index += 2; continue
            if text[index] in "\r\n": output.append(text[index])
            index += 1; continue
        matched = False
        for name, pattern in _RUST_TOKENS:
            match = pattern.match(text, index)
            if not match: continue
            if name == "LINE_COMMENT":
                index = match.end()
            elif name == "BLOCK_OPEN":
                depth = 1; index = match.end()
            else:
                output.append(match.group()); index = match.end()
            matched = True
            break
        if not matched:
            output.append(text[index]); index += 1
    return restore_eof(text, "".join(output))

def remove_matlab_comments(text):
    """MATLAB: '%' line comments, nestable '%{ %}' block comments - but a
    block delimiter ONLY counts when it is alone on its line (per the real
    MATLAB spec); treating a mid-line '%{' as a block-open is a serious bug,
    not just an imprecision - it silently deletes every real line of code
    after it for the rest of the file (no matching '%}' is ever found).
    A "'" is the transpose operator (not a string) when it immediately
    follows an identifier character, ')', ']', '}' or another "'" with no
    space - naively treating every "'" as a string delimiter desyncs on the
    very common `A'` / `A.'` transpose idiom."""
    lines = text.splitlines()
    result, depth, quote = [], 0, None
    transpose_predecessors = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_)]}'.")
    for line in lines:
        stripped = line.strip()
        if depth > 0:
            if stripped == "%{": depth += 1
            elif stripped == "%}": depth -= 1
            result.append("")
            continue
        if stripped == "%{":
            depth = 1; result.append(""); continue
        out, index, length = [], 0, len(line)
        while index < length:
            char = line[index]
            if quote:
                out.append(char)
                if char == quote:
                    if index + 1 < length and line[index + 1] == quote:
                        out.append(quote); index += 2; continue
                    quote = None
                index += 1; continue
            if char == "'":
                if out and out[-1] in transpose_predecessors:
                    out.append(char); index += 1; continue  # transpose operator
                quote = char; out.append(char); index += 1; continue
            if char == '"':
                quote = char; out.append(char); index += 1; continue
            if char == "%":
                break  # rest of line is a real line comment
            out.append(char); index += 1
        result.append("".join(out))
    return restore_eof(text, "\n".join(result))

def remove_java_comments(text):
    output, index, mode, escaped = [], 0, "code", False
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if mode == "text_block":
            if text.startswith('"""', index):
                output.append('"""'); index += 3; mode = "code"
            else: output.append(char); index += 1
            continue
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if mode in ("string", "char"):
            output.append(char)
            if char == "\\": escaped = True
            elif mode == "string" and char == '"': mode = "code"
            elif mode == "char" and char == "'": mode = "code"
            index += 1; continue
        if text.startswith('"""', index):
            output.append('"""'); index += 3; mode = "text_block"; continue
        if char == '"': mode = "string"; output.append(char); index += 1; continue
        if char == "'": mode = "char"; output.append(char); index += 1; continue
        if pair == "//":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


# ---------------------------------------------------------------------------
# JavaScript, TypeScript, JSX and TSX
# ---------------------------------------------------------------------------


def remove_javascript_comments(text, preserve_jsx_comments=False):
    output = []
    index, length, mode = 0, len(text), "code"
    escaped, regex_class = False, False
    previous_significant, previous_word = None, ""
    regex_prefix_chars = set("=([{!?:;,<>+-*%&|^~")
    regex_prefix_words = {"return", "throw", "case", "delete", "typeof", "void", "new", "instanceof", "in", "of", "yield", "await", "else", "do"}

    def can_start_regex():
        return previous_significant is None or previous_significant in regex_prefix_chars or previous_word in regex_prefix_words

    while index < length:
        char, pair = text[index], text[index:index + 2]
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if mode in ("single", "double", "template"):
            output.append(char)
            if char == "\\": escaped = True
            elif (mode == "single" and char == "'") or (mode == "double" and char == '"') or (mode == "template" and char == "`"):
                mode = "code"; previous_significant, previous_word = char, ""
            index += 1; continue
        if mode == "regex":
            output.append(char)
            if char == "\\": escaped = True
            elif char == "[" and not regex_class: regex_class = True
            elif char == "]" and regex_class: regex_class = False
            elif char == "/" and not regex_class:
                mode = "code"; index += 1
                while index < length and (text[index].isalpha() or text[index].isdigit()):
                    output.append(text[index]); index += 1
                previous_significant, previous_word = "/", ""; continue
            index += 1; continue
        if char == "'": mode = "single"; output.append(char); index += 1; continue
        if char == '"': mode = "double"; output.append(char); index += 1; continue
        if char == "`": mode = "template"; output.append(char); index += 1; continue
        if preserve_jsx_comments and text.startswith("{/*", index):
            end = text.find("*/}", index + 3)
            if end == -1: output.append(text[index:]); break
            output.append(text[index:end + 3]); index = end + 3
            previous_significant, previous_word = "}", ""; continue
        if pair == "//":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < length:
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        if char == "/" and can_start_regex():
            mode = "regex"; regex_class = False; output.append(char); index += 1; continue
        output.append(char)
        if char.isalnum() or char in "_$": previous_word += char
        elif not char.isspace(): previous_significant, previous_word = char, ""
        index += 1
    return restore_eof(text, "".join(output))


def remove_jsx_comments(text):
    return remove_javascript_comments(text, preserve_jsx_comments=True)


# ---------------------------------------------------------------------------
# Generic configurable comment engine
#
# Covers every remaining language whose comment rules reduce to "these
# literal tokens start an end-of-line comment" and/or "these open/close
# delimiter pairs bound a block comment", with simple single-character
# string quoting. Written once and parameterized per language via
# functools.partial, instead of duplicating near-identical hand-rolled
# parsers 80+ times.
# ---------------------------------------------------------------------------

def remove_comments_generic(text, *, line_tokens=(), block_specs=(), string_starts=(),
                             doubled_escape=frozenset(), literal_quote_chars=frozenset(),
                             backslash_escape=True, preserve_shebang=False):
    """Configurable comment stripper.

    line_tokens: literal tokens that start an end-of-line comment, tried in
      the given order at every position (list longer/more specific tokens
      before shorter ones they overlap with, e.g. '///' before '//').
    block_specs: (open, close, nestable) triples, tried in the given order.
    string_starts: single characters that open a quoted string/char literal.
    doubled_escape: subset of string_starts where doubling the delimiter
      ("" / '') is the escape for a literal delimiter inside the string
      (Pascal, Ada, VBA, MATLAB, VHDL, ...).
    literal_quote_chars: subset of string_starts with NO escape mechanism
      at all - the very next occurrence of the same character always closes
      the string (e.g. a single-quoted Bash string).
    backslash_escape: whether a backslash escapes the next character, for
      string_starts not covered by doubled_escape/literal_quote_chars.
    preserve_shebang: keep a leading '#!' first line untouched.
    """
    output, index, length = [], 0, len(text)
    quote = None
    while index < length:
        if preserve_shebang and index == 0 and text.startswith("#!"):
            newline_pos = text.find("\n")
            end = newline_pos if newline_pos != -1 else length
            output.append(text[index:end]); index = end; continue
        char = text[index]
        if quote:
            output.append(char)
            if quote in literal_quote_chars:
                if char == quote: quote = None
                index += 1; continue
            if quote in doubled_escape and char == quote:
                if index + 1 < length and text[index + 1] == quote:
                    output.append(quote); index += 2; continue
                quote = None; index += 1; continue
            if backslash_escape and char == "\\":
                if index + 1 < length: output.append(text[index + 1])
                index += 2; continue
            if char == quote: quote = None
            index += 1; continue
        if char in string_starts:
            quote = char; output.append(char); index += 1; continue
        matched_block = next((spec for spec in block_specs if text.startswith(spec[0], index)), None)
        if matched_block:
            open_tok, close_tok, nestable = matched_block
            depth, index = 1, index + len(open_tok)
            while index < length and depth > 0:
                if nestable and text.startswith(open_tok, index):
                    depth += 1; index += len(open_tok); continue
                if text.startswith(close_tok, index):
                    depth -= 1; index += len(close_tok); continue
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        matched_line = next((token for token in line_tokens if text.startswith(token, index)), None)
        if matched_line:
            while index < length and text[index] not in "\r\n": index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))

def remove_line_start_comments(text, tokens):
    """Strip a comment only when one of ``tokens`` is the very first
    non-whitespace content of the line - the safe rule for languages where
    the token doubles as a normal operator elsewhere (Stata/GAMS '*', Sed/
    Tcl '#'), so stripping it anywhere on the line risks deleting real code."""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if any(stripped.startswith(token) for token in tokens):
            lines.append(line[:len(line) - len(stripped)].rstrip())
        else:
            lines.append(line)
    return restore_eof(text, "\n".join(lines))

_PERL_HEREDOC_RE = re.compile(r'<<(~?)\s*(?:"([^"]*)"|\'([^\']*)\'|([A-Za-z_]\w*))')

_BASH_HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_][A-Za-z0-9_]*))")

_TF_HEREDOC_RE = re.compile(r"<<(-?)\s*([A-Za-z_][A-Za-z0-9_]*)")

def remove_terraform_comments(text):
    """HCL/Terraform: '#' and '//' line comments, '/* */' block comments
    (persisted across lines, non-nesting), and <<EOF / <<-EOF heredocs whose
    body must be left verbatim - same bug class as Bash/Perl heredocs: a
    '#' inside heredoc body content is data, not a comment."""
    lines = text.splitlines()
    result, in_block, heredoc_marker, heredoc_indented = [], False, None, False
    for line in lines:
        if heredoc_marker is not None:
            result.append(line)
            if (line.strip() if heredoc_indented else line) == heredoc_marker:
                heredoc_marker = None
            continue
        out, index, length = [], 0, len(line)
        while index < length:
            if in_block:
                if line.startswith("*/", index): in_block = False; index += 2; continue
                index += 1; continue
            char = line[index]
            if char == '"':
                out.append(char); index += 1
                while index < length:
                    out.append(line[index])
                    if line[index] == "\\" and index + 1 < length:
                        index += 1; out.append(line[index]); index += 1; continue
                    if line[index] == '"': index += 1; break
                    index += 1
                continue
            if line.startswith("<<", index):
                match = _TF_HEREDOC_RE.match(line, index)
                if match:
                    heredoc_indented = bool(match.group(1)); heredoc_marker = match.group(2)
                    out.append(line[index:match.end()]); index = match.end(); continue
            if line.startswith("/*", index):
                in_block = True; index += 2; continue
            if line.startswith("//", index) or char == "#":
                break  # rest of line is a real comment
            out.append(char); index += 1
        result.append("".join(out))
    return restore_eof(text, "\n".join(result))

def remove_bash_comments(text):
    """Bash needs several things a plain line-by-line hash scanner gets wrong:
    (1) single/double-quoted strings may legitimately span multiple lines,
    so quote state must persist ACROSS lines, not reset each line - and
    single-quoted strings have NO escape mechanism at all (a backslash
    inside '...' is a literal character, unlike double-quoted strings);
    (2) heredoc bodies (<<EOF ... EOF) are verbatim data, and a '#' line
    in there is data, not a comment - the same class of bug as Perl's
    heredocs, just for shell scripts instead;
    (3) '<<' is ALSO the arithmetic left-shift operator inside $((...)) -
    e.g. $((n << shift_amount)) - and must never be mistaken for a heredoc
    there, or the "marker" (an ordinary variable name) is never found and
    every line for the rest of the file silently stops being scanned for
    comments."""
    lines = text.splitlines()
    result, quote, heredoc_marker, heredoc_indented, arith_depth = [], None, None, False, 0
    for line_no, line in enumerate(lines):
        if heredoc_marker is not None:
            result.append(line)
            if (line.lstrip("\t") if heredoc_indented else line) == heredoc_marker:
                heredoc_marker = None
            continue
        if line_no == 0 and quote is None and line.startswith("#!"):
            result.append(line); continue
        out, index, length = [], 0, len(line)
        while index < length:
            char = line[index]
            if quote:
                out.append(char)
                if quote == "'":
                    if char == "'": quote = None
                else:  # quote == '"' - backslash escapes the next character
                    if char == "\\" and index + 1 < length:
                        out.append(line[index + 1]); index += 2; continue
                    if char == '"': quote = None
                index += 1; continue
            if char in ("'", '"'):
                quote = char; out.append(char); index += 1; continue
            if line.startswith("$((", index):
                arith_depth += 2; out.append("$(("); index += 3; continue
            if arith_depth > 0:
                if char == "(": arith_depth += 1
                elif char == ")": arith_depth -= 1
                out.append(char); index += 1; continue
            if line.startswith("<<", index):
                match = _BASH_HEREDOC_RE.match(line, index)
                if match:
                    heredoc_indented = bool(match.group(1))
                    heredoc_marker = match.group(2) or match.group(3) or match.group(4)
                    out.append(line[index:match.end()]); index = match.end(); continue
            if char == "#": break  # rest of the line is a real comment
            out.append(char); index += 1
        result.append("".join(out))
    return restore_eof(text, "\n".join(result))

def remove_perl_comments(text):
    """Perl: '#' line comments, but must NOT look inside a heredoc body -
    <<TAG / <<"TAG" / <<'TAG' / <<~TAG bodies are verbatim data until a line
    that is exactly TAG (or, for the '~' indented form, TAG after stripping
    leading whitespace); a '#' in there is data, not a comment. Handles one
    heredoc start per line, which covers the vast majority of real code."""
    lines = text.splitlines()
    result, i, total = [], 0, len(lines)
    while i < total:
        line = lines[i]
        match = _PERL_HEREDOC_RE.search(line)
        result.append(remove_comments_generic(line, line_tokens=("#",), string_starts=('"', "'"), backslash_escape=True))
        i += 1
        if match:
            indented, tag = bool(match.group(1)), match.group(2) or match.group(3) or match.group(4)
            while i < total:
                body_line = lines[i]
                result.append(body_line); i += 1
                if (body_line.strip() if indented else body_line) == tag: break
    return restore_eof(text, "\n".join(result))

def remove_stata_comments(text):
    """Stata mixes a line-start-only '*' with an anywhere '//' and a '/* */'
    block; the ///-line-continuation-comment form is intentionally not
    handled (too easy to misfire on)."""
    return remove_comments_generic(
        remove_line_start_comments(text, ("*",)),
        line_tokens=("//",), block_specs=[("/*", "*/", False)],
        string_starts=('"',), backslash_escape=True,
    )

def remove_fortran_fixed_comments(text):
    """Fixed-form Fortran (.f/.for): a comment is a 'C', 'c' or '*' in
    column 1 (no leading whitespace tolerated) - the whole line is dropped."""
    lines = []
    for line in text.splitlines():
        lines.append("" if line[:1] in ("C", "c", "*") else line)
    return restore_eof(text, "\n".join(lines))

def remove_abap_comments(text):
    """ABAP: '*' as the very first character of a line comments out the
    whole line; a bare '"' anywhere else on a line comments to end of line.
    ABAP text literals are single-quoted or backtick-delimited, so a
    double-quote is unambiguous and never itself needs string protection."""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*"):
            lines.append(line[:len(line) - len(stripped)].rstrip()); continue
        quote, cut = None, None
        for i, char in enumerate(line):
            if quote:
                if char == quote: quote = None
                continue
            if char in ("'", "`"):
                quote = char; continue
            if char == '"':
                cut = i; break
        lines.append((line if cut is None else line[:cut]).rstrip())
    return restore_eof(text, "\n".join(lines))

# ---------------------------------------------------------------------------
# Dart
# ---------------------------------------------------------------------------

def remove_dart_comments(text):
    """Dart: '//' and '/* */' (non-nesting), plus single/double and
    triple-quoted strings. Raw strings (r'...' / r"...") are detected via
    a preceding bare 'r'/'R', so backslashes inside them are NOT escapes."""
    output, index, length = [], 0, len(text)
    mode, escaped, raw = "code", False, False
    while index < length:
        char, pair = text[index], text[index:index + 2]
        if mode in ("triple_single", "triple_double"):
            delim = "'''" if mode == "triple_single" else '"""'
            if text.startswith(delim, index):
                output.append(delim); index += 3; mode = "code"; raw = False; continue
            if not raw and escaped:
                output.append(char); escaped = False; index += 1; continue
            if not raw and char == "\\":
                output.append(char); escaped = True; index += 1; continue
            output.append(char); index += 1; continue
        if mode in ("single", "double"):
            output.append(char)
            if not raw and escaped:
                escaped = False; index += 1; continue
            if not raw and char == "\\":
                escaped = True; index += 1; continue
            if (mode == "single" and char == "'") or (mode == "double" and char == '"'):
                mode = "code"; raw = False
            index += 1; continue
        def is_raw_prefix(i):
            return i > 0 and text[i - 1] in ("r", "R") and (i < 2 or not (text[i - 2].isalnum() or text[i - 2] == "_"))
        if text.startswith("'''", index):
            raw = is_raw_prefix(index); mode = "triple_single"; output.append("'''"); index += 3; continue
        if text.startswith('"""', index):
            raw = is_raw_prefix(index); mode = "triple_double"; output.append('"""'); index += 3; continue
        if char == "'":
            raw = is_raw_prefix(index); mode = "single"; output.append(char); index += 1; continue
        if char == '"':
            raw = is_raw_prefix(index); mode = "double"; output.append(char); index += 1; continue
        if pair == "//":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < length:
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))

# ---------------------------------------------------------------------------
# PHP, SQL, XML and Lua
# ---------------------------------------------------------------------------


def remove_php_comments(text):
    """Remove PHP comments while preserving Parsedown strings and escapes."""
    output, index, length = [], 0, len(text)
    in_php, quote = False, None
    while index < length:
        if not in_php and text.startswith("<?", index):
            in_php = True; output.append("<?"); index += 2; continue
        if not in_php:
            if text.startswith("<!--", index):
                index += 4
                while index < length:
                    if text.startswith("-->", index): index += 3; break
                    if text[index] in "\r\n": output.append(text[index])
                    index += 1
                continue
            output.append(text[index]); index += 1; continue
        char, pair = text[index], text[index:index + 2]
        if quote == "'":
            output.append(char)
            if char == "\\" and index + 1 < length and text[index + 1] in ("\\", "'"):
                output.append(text[index + 1]); index += 2; continue
            if char == "'": quote = None
            index += 1; continue
        if quote == '"':
            output.append(char)
            if char == "\\" and index + 1 < length:
                output.append(text[index + 1]); index += 2; continue
            if char == '"': quote = None
            index += 1; continue
        if char == "'": quote = "'"; output.append(char); index += 1; continue
        if char == '"': quote = '"'; output.append(char); index += 1; continue
        if pair == "?>": in_php = False; output.append(pair); index += 2; continue
        if pair == "//" or char == "#":
            while index < length and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < length:
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_sql_comments(text):
    output, index, quote = [], 0, None
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    output.append(quote); index += 2; continue
                quote = None
            index += 1; continue
        if char in ('"', "'"): quote = char; output.append(char); index += 1; continue
        if pair == "--" or char == "#":
            while index < len(text) and text[index] not in "\r\n": index += 1
            continue
        if pair == "/*":
            index += 2
            while index < len(text):
                if text.startswith("*/", index): index += 2; break
                if text[index] in "\r\n": output.append(text[index])
                index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


def remove_xml_comments(text):
    return restore_eof(text, re.sub(r"<!--.*?-->", preserve_newlines, text, flags=re.DOTALL))

_HTML_STYLE_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
_HTML_SCRIPT_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.IGNORECASE | re.DOTALL)
_HTML_SCRIPT_TYPE_RE = re.compile(r'type\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_HTML_JS_SCRIPT_TYPES = ("", "text/javascript", "application/javascript", "module", "text/babel")

def remove_html_comments(text):
    """Like remove_xml_comments, but additionally cleans embedded <style>
    blocks with the real CSS comment rules and <script> blocks (when they
    are - or default to - JavaScript) with the real JS comment rules,
    since browsers treat those as separate embedded languages with their
    own comment syntax that a plain <!-- --> pass never touches."""
    def clean_style(match):
        return match.group(1) + remove_c_comments(match.group(2)) + match.group(3)

    def clean_script(match):
        open_tag = match.group(1)
        type_match = _HTML_SCRIPT_TYPE_RE.search(open_tag)
        script_type = type_match.group(1).lower() if type_match else ""
        if script_type in _HTML_JS_SCRIPT_TYPES or "javascript" in script_type:
            return open_tag + remove_javascript_comments(match.group(2)) + match.group(3)
        return match.group(0)  # e.g. application/json, text/template - not JS, leave untouched

    text = _HTML_STYLE_RE.sub(clean_style, text)
    text = _HTML_SCRIPT_RE.sub(clean_script, text)
    return remove_xml_comments(text)

def remove_lua_comments(text):
    output, index, length = [], 0, len(text)
    quote, escaped, long_end = None, False, None
    def bracket_end(pos):
        if pos >= length or text[pos] != "[": return None
        cursor = pos + 1
        while cursor < length and text[cursor] == "=": cursor += 1
        return "]" + text[pos + 1:cursor] + "]" if cursor < length and text[cursor] == "[" else None
    while index < length:
        char = text[index]
        if long_end:
            if text.startswith(long_end, index): output.append(long_end); index += len(long_end); long_end = None
            else: output.append(char); index += 1
            continue
        if escaped: output.append(char); escaped = False; index += 1; continue
        if quote:
            output.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            index += 1; continue
        if char in ('"', "'"): quote = char; output.append(char); index += 1; continue
        opening = bracket_end(index)
        if opening: output.append(text[index:index + len(opening)]); index += len(opening); long_end = opening; continue
        if text.startswith("--", index):
            index += 2; end = bracket_end(index)
            if end:
                index += len(end)
                while index < length:
                    if text.startswith(end, index): index += len(end); break
                    if text[index] in "\r\n": output.append(text[index])
                    index += 1
            else:
                while index < length and text[index] not in "\r\n": index += 1
            continue
        output.append(char); index += 1
    return restore_eof(text, "".join(output))


# ---------------------------------------------------------------------------
# Encoding and line endings
# ---------------------------------------------------------------------------


def detect_newline(text):
    if "\r\n" in text: return "\r\n"
    if "\r" in text and "\n" not in text: return "\r"
    return "\n"


def apply_newline_style(text, newline):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if newline == "\n" else normalized.replace("\n", newline)


def decode_source_file(path):
    with open(path, "rb") as file: data = file.read()
    if data.startswith(b"\xef\xbb\xbf"): encoding, text = "utf-8-sig", data.decode("utf-8-sig")
    elif data.startswith(b"\xff\xfe\x00\x00"): encoding, text = "utf-32-le-bom", data[4:].decode("utf-32-le")
    elif data.startswith(b"\x00\x00\xfe\xff"): encoding, text = "utf-32-be-bom", data[4:].decode("utf-32-be")
    elif data.startswith(b"\xff\xfe"): encoding, text = "utf-16-le-bom", data[2:].decode("utf-16-le")
    elif data.startswith(b"\xfe\xff"): encoding, text = "utf-16-be-bom", data[2:].decode("utf-16-be")
    else:
        try: encoding, text = "utf-8", data.decode("utf-8")
        except UnicodeDecodeError:
            encoding = "cp1252" if any(0x80 <= b < 0xA0 for b in data) else "latin-1"
            text = data.decode(encoding)
    return text, encoding, detect_newline(text), len(data)


def encode_source_text(text, encoding):
    if encoding == "utf-16-le-bom": return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding == "utf-16-be-bom": return b"\xfe\xff" + text.encode("utf-16-be")
    if encoding == "utf-32-le-bom": return b"\xff\xfe\x00\x00" + text.encode("utf-32-le")
    if encoding == "utf-32-be-bom": return b"\x00\x00\xfe\xff" + text.encode("utf-32-be")
    return text.encode(encoding)


# ---------------------------------------------------------------------------
# Verification: after stripping comments, optionally re-check the result with
# the REAL syntax checker of that language (not another heuristic parser) -
# so "the program still works" is a verified fact for that file, not a hope.
# A verifier returns (True, "") = valid, (False, message) = broken - the file
# is then left untouched - or (None, reason) = could not check (tool missing
# on this machine), which is reported but does not block writing.
# ---------------------------------------------------------------------------

_tool_cache = {}

def _tool_available(name):
    if name not in _tool_cache: _tool_cache[name] = shutil.which(name) is not None
    return _tool_cache[name]

def _run_external_check(command, text, suffix, tool_name):
    if not _tool_available(tool_name): return None, f"{tool_name} nicht auf diesem System gefunden"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as tmp_file:
            tmp_file.write(text); tmp_path = tmp_file.name
        full_command = [tmp_path if part == "{file}" else part for part in command]
        result = subprocess.run(full_command, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, (result.stderr or result.stdout).strip()
    except subprocess.TimeoutExpired:
        return None, f"{tool_name}-Check hat das 30s-Timeout überschritten"
    except OSError as error:
        return None, f"{tool_name} konnte nicht ausgeführt werden: {error}"
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except OSError: pass

def verify_python(text):
    try: ast.parse(text); return True, ""
    except SyntaxError as error: return False, str(error)

def verify_json(text):
    try: json.loads(text); return True, ""
    except json.JSONDecodeError as error: return False, str(error)

def verify_node_js(text):
    # .js can be CommonJS or ESM - try both, since node --check needs to know
    # which grammar to use and there is no reliable way to tell from content alone.
    for suffix in (".cjs", ".mjs"):
        ok, message = _run_external_check(["node", "--check", "{file}"], text, suffix, "node")
        if ok: return True, ""
    return ok, message

def verify_node_module(text):
    return _run_external_check(["node", "--check", "{file}"], text, ".mjs", "node")

def verify_node_commonjs(text):
    return _run_external_check(["node", "--check", "{file}"], text, ".cjs", "node")

def verify_gcc(text): return _run_external_check(["gcc", "-fsyntax-only", "-w", "{file}"], text, ".c", "gcc")
def verify_gxx(text): return _run_external_check(["g++", "-fsyntax-only", "-w", "{file}"], text, ".cpp", "g++")
def verify_perl(text): return _run_external_check(["perl", "-c", "{file}"], text, ".pl", "perl")
def verify_bash(text): return _run_external_check(["bash", "-n", "{file}"], text, ".sh", "bash")
def verify_php(text): return _run_external_check(["php", "-l", "{file}"], text, ".php", "php")
def verify_ruby(text): return _run_external_check(["ruby", "-c", "{file}"], text, ".rb", "ruby")
def verify_lua(text): return _run_external_check(["luac", "-p", "{file}"], text, ".lua", "luac")
def verify_gofmt(text): return _run_external_check(["gofmt", "-e", "{file}"], text, ".go", "gofmt")

VERIFIERS = {
    ".py": verify_python,
    ".json": verify_json,
    ".js": verify_node_js, ".cjs": verify_node_commonjs, ".mjs": verify_node_module,
    ".c": verify_gcc, ".h": verify_gcc,
    ".cpp": verify_gxx, ".cc": verify_gxx, ".hpp": verify_gxx,
    ".pl": verify_perl, ".pm": verify_perl,
    ".sh": verify_bash,
    ".php": verify_php,
    ".rb": verify_ruby,
    ".lua": verify_lua,
    ".go": verify_gofmt,
}
# Deliberately not wired up, even where a tool commonly exists:
#  - TypeScript (.ts/.tsx): tsc needs a tsconfig/project context to check
#    reliably; a bare per-file check produces too many false failures.
#  - Java: javac needs the file name to match the public class name and
#    typically a classpath for dependencies - not safe as a bare per-file check.
#  - Rust: rustc has no stable syntax-only flag; a real check needs crate
#    dependencies most single files don't carry, so it would misfire often.
# For these, review the diff report (--debug-diff) instead of relying on --verify.

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

HANDLERS = {}
for ext in (".toml", ".mojo", ".ex", ".exs"): HANDLERS[ext] = remove_hash_comments
HANDLERS[".tf"] = remove_terraform_comments
HANDLERS[".sh"] = remove_bash_comments
HANDLERS[".py"] = remove_python_comments
HANDLERS[".rb"] = remove_ruby_comments
for ext in (".yml", ".yaml"): HANDLERS[ext] = remove_yaml_comments
for ext in (".cfg", ".conf", ".properties"): HANDLERS[ext] = remove_config_hash_comments
HANDLERS[".ini"] = remove_ini_comments
# C-family, non-nesting block comments: also covers GLSL/HLSL shaders, Solidity,
# Apex triggers, Verilog/SystemVerilog, Move, Cairo, X10, Carbon, Ballerina, ReScript.
for ext in (".cs", ".c", ".cpp", ".cc", ".h", ".hpp", ".go", ".css", ".scss", ".less",
            ".glsl", ".hlsl", ".vert", ".frag", ".geom", ".comp", ".sol", ".trigger",
            ".v", ".sv", ".move", ".cairo", ".x10", ".carbon", ".bal", ".res", ".mm"):
    HANDLERS[ext] = remove_c_comments
# C-family, nesting block comments (language spec explicitly allows /* /* */ */).
for ext in (".swift", ".kt", ".kts", ".odin", ".chpl", ".scala"): HANDLERS[ext] = remove_c_comments_nestable
HANDLERS[".rs"] = remove_rust_comments
for ext in (".java", ".groovy"): HANDLERS[ext] = remove_java_comments
for ext in (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts", ".as"): HANDLERS[ext] = remove_javascript_comments
for ext in (".jsx", ".tsx"): HANDLERS[ext] = remove_jsx_comments
HANDLERS[".dart"] = remove_dart_comments
for ext in (".ada", ".adb", ".ads"): HANDLERS[ext] = remove_ada_comments
for ext in (".bas", ".cls", ".frm", ".vb"): HANDLERS[ext] = remove_vba_comments  # VBA, VB.NET and classic BASIC share this comment syntax
HANDLERS[".jl"] = remove_julia_comments
HANDLERS.update({".html": remove_html_comments, ".htm": remove_html_comments, ".php": remove_php_comments, ".sql": remove_sql_comments, ".xml": remove_xml_comments, ".xaml": remove_xml_comments, ".svg": remove_xml_comments, ".lua": remove_lua_comments, ".svelte": remove_html_comments})

# ---------------------------------------------------------------------------
# Generic-engine language configs. Each entry maps one or more extensions to
# a functools.partial(remove_comments_generic, **kwargs) instance.
# ---------------------------------------------------------------------------
_DASH_NESTED_BLOCK = dict(line_tokens=("--",), block_specs=[("{-", "-}", True)], string_starts=('"',), backslash_escape=True)  # Haskell-family
GENERIC_CONFIGS = {
    (".r",): dict(line_tokens=("#",), string_starts=('"', "'"), backslash_escape=True, preserve_shebang=True),
    (".fish", ".zsh"): dict(line_tokens=("#",), string_starts=('"', "'"), literal_quote_chars={"'"}, backslash_escape=True, preserve_shebang=True),
    (".awk",): dict(line_tokens=("#",), string_starts=('"',), backslash_escape=True, preserve_shebang=True),
    (".erl", ".hrl"): dict(line_tokens=("%",), string_starts=('"', "'"), backslash_escape=True),
    (".ps1", ".psm1", ".psd1"): dict(line_tokens=("#",), block_specs=[("<#", "#>", False)], string_starts=('"', "'"), doubled_escape={"'", '"'}, backslash_escape=False),
    (".pas", ".dpr", ".pp"): dict(line_tokens=("//",), block_specs=[("{", "}", False), ("(*", "*)", False)], string_starts=("'",), doubled_escape={"'"}),
    (".mod",): dict(block_specs=[("(*", "*)", True)], string_starts=("'", '"'), literal_quote_chars={"'", '"'}),                   # Modula-2
    (".f90", ".f95", ".f03", ".f08"): dict(line_tokens=("!",), string_starts=('"', "'"), doubled_escape={'"', "'"}, backslash_escape=False),
    (".cbl", ".cob"): dict(line_tokens=("*>",), string_starts=('"', "'"), backslash_escape=True),                                  # free-format COBOL only
    (".ml", ".mli"): dict(block_specs=[("(*", "*)", True)], string_starts=('"',), backslash_escape=True),                          # OCaml
    (".rkt",): dict(line_tokens=(";",), block_specs=[("#|", "|#", True)], string_starts=('"',), backslash_escape=True),
    (".lisp", ".lsp"): dict(line_tokens=(";",), block_specs=[("#|", "|#", True)], string_starts=('"',), backslash_escape=True),
    (".scm", ".ss"): dict(line_tokens=(";",), block_specs=[("#|", "|#", True)], string_starts=('"',), backslash_escape=True),
    (".clj", ".cljs", ".cljc"): dict(line_tokens=(";",), string_starts=('"',), backslash_escape=True),
    (".fs", ".fsx", ".fsi"): dict(line_tokens=("//",), block_specs=[("(*", "*)", True)], string_starts=('"',), backslash_escape=True),  # F#
    (".cr",): dict(line_tokens=("#",), string_starts=('"',), backslash_escape=True, preserve_shebang=True),                        # Crystal
    (".nim",): dict(line_tokens=("#",), block_specs=[("#[", "]#", True)], string_starts=('"',), backslash_escape=True),
    (".zig",): dict(line_tokens=("//",), string_starts=('"',), backslash_escape=True),
    (".vhd", ".vhdl"): dict(line_tokens=("--",), block_specs=[("/*", "*/", False)], string_starts=('"',), doubled_escape={'"'}),
    (".coffee",): dict(line_tokens=("#",), block_specs=[("###", "###", False)], string_starts=('"', "'"), backslash_escape=True),
    (".cfm", ".cfc"): dict(block_specs=[("<!---", "--->", False)]),                                                                 # tag-level only, cfscript regions not parsed
    (".tcl",): "line_start:#",
    (".elm",): dict(_DASH_NESTED_BLOCK),
    (".purs",): dict(_DASH_NESTED_BLOCK),
    (".idr",): dict(_DASH_NESTED_BLOCK),
    (".agda",): dict(_DASH_NESTED_BLOCK),
    (".hbs", ".handlebars"): dict(block_specs=[("{{!--", "--}}", False), ("{{!", "}}", False)]),
    (".liquid",): dict(block_specs=[("{% comment %}", "{% endcomment %}", False)]),
    (".sas",): dict(block_specs=[("/*", "*/", False)], string_starts=('"', "'"), backslash_escape=True),                           # only /* */ - see note on '*...;' form
    (".wl",): dict(block_specs=[("(*", "*)", True)], string_starts=('"',), backslash_escape=True),                                 # Wolfram Language
    (".gms",): "line_start:*",
    (".st",): dict(block_specs=[('"', '"', False)], string_starts=("'",), doubled_escape={"'"}),                                   # Smalltalk: "..." IS the comment, '...' is a string
    (".pli", ".pl1"): dict(block_specs=[("/*", "*/", False)], string_starts=('"', "'"), doubled_escape={'"', "'"}),
    (".fth",): dict(line_tokens=("\\",), block_specs=[("(", ")", False)]),                                                          # Forth (.fs would collide with F#)
    (".sml", ".sig"): dict(block_specs=[("(*", "*)", True)], string_starts=('"',), backslash_escape=True),
    (".asm", ".s"): dict(line_tokens=(";",), string_starts=('"', "'"), literal_quote_chars={'"', "'"}),
    (".logo",): dict(line_tokens=(";",), string_starts=('"',), backslash_escape=True),
    (".abap",): "abap",
    (".red",): dict(line_tokens=(";",), string_starts=('"',), backslash_escape=True),
    (".io",): dict(line_tokens=("//", "#"), block_specs=[("/*", "*/", False)], string_starts=('"',), backslash_escape=True),
    (".factor",): dict(line_tokens=("! ",), string_starts=('"',), backslash_escape=True),
    (".ijs",): dict(line_tokens=("NB.",), string_starts=('"',), doubled_escape={'"'}),
    (".apl", ".dyalog"): dict(line_tokens=("⍝",), string_starts=('"',), doubled_escape={'"'}),
    (".sed",): "line_start:#",
    (".vy",): dict(line_tokens=("#",), string_starts=('"', "'"), backslash_escape=True),                                           # Vyper
    (".do", ".ado"): "stata",
    (".f", ".for"): "fortran_fixed",
}
HANDLERS[".m"] = remove_matlab_comments
for ext in (".pl", ".pm"): HANDLERS[ext] = remove_perl_comments  # .pl defaults here over Prolog - see note below
for extensions, config in GENERIC_CONFIGS.items():
    if config == "abap": handler = remove_abap_comments
    elif config == "stata": handler = remove_stata_comments
    elif config == "fortran_fixed": handler = remove_fortran_fixed_comments
    elif isinstance(config, str) and config.startswith("line_start:"):
        handler = functools.partial(remove_line_start_comments, tokens=(config.split(":", 1)[1],))
    else:
        handler = functools.partial(remove_comments_generic, **config)
    for ext in extensions: HANDLERS[ext] = handler

# ---------------------------------------------------------------------------
# Deliberately NOT auto-mapped:
#  - LabVIEW (G) and Ladder Logic: graphical/binary formats, no text comment
#    syntax to strip from source.
#  - K/Q (kdb+): '/' means division or "start of line comment" depending on
#    context (and a lone '/'/'\' line toggles a block); too ambiguous to
#    strip safely without risking silently deleting real code.
#  - COBOL fixed-format (column 7 indicator), RPG, Algol, Simula: column-
#    or dialect-specific rules too inconsistent across variants to encode
#    with confidence; only free-format COBOL (.cbl/.cob, '*>') is handled.
#  - Prolog (.pl) and Coq (.v): both extensions are already claimed above by
#    the far more common Perl and Verilog respectively. Wire up Prolog/Coq
#    yourself via remove_comments_generic(line_tokens=("%",), block_specs=
#    [("/*","*/",False)], string_starts=('"',"'")) / block_specs=[("(*","*)",True)]
#    if you use a distinct extension for them.
#  - Miranda (.mira is not a real convention) and MATLAB-vs-Objective-C's
#    shared ".m": MATLAB claims ".m" above since it's the more common of the
#    two on that extension; Objective-C implementation files sharing ".m"
#    won't be cleaned correctly this way (.h/.mm already map to C-style).
# ---------------------------------------------------------------------------

DELETE_TYPES = {".md", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".mp3", ".mp4", ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".rar", ".7z", ".gz", ".pyc", ".class", ".jar"}


# ---------------------------------------------------------------------------
# Post-processing and reporting helpers
# ---------------------------------------------------------------------------


def safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def normalize_extensions(values):
    return {value.lower() if value.startswith(".") else "." + value.lower() for value in values}


def classify_lines(source_text, stripped_text):
    """Classify every physical line of source_text as blank / comment-only / code.

    ``stripped_text`` must be the comment-stripped version of source_text with
    line positions preserved (as every handler in this script guarantees), so
    lines can be compared positionally: a line that was non-blank in the
    source but is blank after stripping was pure comment; everything else
    non-blank is real code (including code with a trailing comment removed).
    """
    source_lines = source_text.splitlines()
    stripped_lines = stripped_text.splitlines()
    bucket = new_loc_bucket()
    bucket["total"] = len(source_lines)
    for index, line in enumerate(source_lines):
        if line.strip() == "":
            bucket["blank"] += 1
        else:
            stripped_line = stripped_lines[index] if index < len(stripped_lines) else ""
            if stripped_line.strip() == "":
                bucket["comment"] += 1
            else:
                bucket["code"] += 1
    return bucket


def add_loc_bucket(target, addition):
    for category in LOC_CATEGORIES:
        target[category] += addition[category]


def format_loc_change(before, after):
    delta = after - before
    percent = (delta / before * 100) if before else 0.0
    sign = "+" if delta > 0 else ("-" if delta < 0 else "")
    return f"{before:>8,} -> {after:>8,}  ({sign}{abs(percent):.1f}%)"


def loc_summary_rows(before_bucket, after_bucket):
    """Yield (label, before, after) rows covering every LoC definition someone might want:
    total lines (incl. blanks and comments), blank lines, non-blank lines (code+comments),
    comment-only lines, and pure code lines (no comments, no blanks)."""
    non_blank_before = before_bucket["total"] - before_bucket["blank"]
    non_blank_after = after_bucket["total"] - after_bucket["blank"]
    return [
        ("Total lines (incl. blanks/comments)", before_bucket["total"], after_bucket["total"]),
        ("Blank lines", before_bucket["blank"], after_bucket["blank"]),
        ("Non-blank lines (incl. comments)", non_blank_before, non_blank_after),
        ("Comment-only lines", before_bucket["comment"], after_bucket["comment"]),
        ("Code lines (no blanks/comments)", before_bucket["code"], after_bucket["code"]),
    ]


def print_loc_by_type_table(by_extension):
    """Print a grid-aligned before/after table of LoC categories per file extension.

    Each category gets its own before-width and after-width (instead of one shared
    width for the whole line), so the '->' lines up across rows even when file counts
    span from single digits to six-figure totals.
    """
    if not by_extension:
        return
    print("\nLoC by file type (before -> after):")
    categories = ("code", "comment", "blank", "total")
    exts = sorted(by_extension)
    ext_width = max(len(ext) for ext in exts)
    before_width = {category: max(len(f"{by_extension[ext]['before'][category]:,}") for ext in exts) for category in categories}
    after_width = {category: max(len(f"{by_extension[ext]['after'][category]:,}") for ext in exts) for category in categories}
    col_width = {category: max(len(category.capitalize()), before_width[category] + 4 + after_width[category]) for category in categories}

    def cell(ext, category):
        before = by_extension[ext]["before"][category]
        after = by_extension[ext]["after"][category]
        return f"{before:>{before_width[category]},} -> {after:<{after_width[category]},}"

    header = "  " + "Type".ljust(ext_width) + "   " + "   ".join(category.capitalize().ljust(col_width[category]) for category in categories)
    print(header)
    for ext in exts:
        row = "  " + ext.ljust(ext_width) + "   " + "   ".join(cell(ext, category).ljust(col_width[category]) for category in categories)
        print(row)


def collapse_blank_lines(text, mode):
    """Reduce ballast left behind by comment removal.

    mode == "squeeze": collapse runs of 2+ consecutive blank lines into one.
    mode == "drop": remove all blank lines entirely.
    mode == "keep": no-op (default, preserves original behavior).
    """
    if mode == "keep":
        return text
    lines = text.split("\n")
    if mode == "drop":
        lines = [line for line in lines if line.strip() != ""]
    elif mode == "squeeze":
        squeezed, previous_blank = [], False
        for line in lines:
            blank = line.strip() == ""
            if blank and previous_blank:
                continue
            squeezed.append(line)
            previous_blank = blank
        lines = squeezed
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optimized HTML report
# ---------------------------------------------------------------------------

CSS = r"""
:root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--head:#21262d;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--blue:#58a6ff;--green:#3fb950;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1800px;margin:auto}h1{color:var(--blue);overflow-wrap:anywhere}a{color:var(--blue);text-decoration:none}.banner,.metadata,.navigation,.section,.card{background:var(--panel);border:1px solid var(--border);border-radius:8px}.banner{margin-bottom:24px;overflow:hidden}.banner-title{padding:16px;text-align:center;font-size:24px;font-weight:700;background:var(--head)}.banner-meta{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)}.banner-meta>div{padding:13px 16px;background:var(--panel)}.banner-meta span{display:block;color:var(--muted);font-size:12px}.metadata,.navigation{padding:16px;margin-bottom:24px}.metadata-row{display:flex;gap:12px;margin:5px 0}.metadata-label{min-width:145px;color:var(--muted)}.summary{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}.card{min-width:180px;padding:16px}.value{display:block;margin-top:6px;font-size:28px;font-weight:700}.red{color:var(--red)}.green{color:var(--green)}.section{margin-bottom:28px;overflow:hidden}.section-title{padding:12px 16px;margin:0;background:var(--head);border-bottom:1px solid var(--border)}.controls,.filter-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border)}button,input{padding:8px 12px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:7px;font:inherit}button{cursor:pointer}button.active{color:#fff;background:#1f6feb}.note,.muted{color:var(--muted);font-size:12px}.view{display:none}.view.active{display:block}.wrap{overflow:auto}.diff{width:max-content;min-width:100%;border-collapse:collapse;table-layout:auto;font:13px/1.5 Consolas,"Cascadia Code",monospace}.diff th,.diff td{padding:6px 9px;border:1px solid var(--border);vertical-align:top}.num{width:var(--line-width,6ch);text-align:right;color:var(--muted);white-space:nowrap}.codecell{min-width:420px;white-space:pre;overflow-wrap:normal;word-break:normal}.old{background:#3b2024}.new{background:#153828}.same,.empty-side{background:var(--panel)!important;color:var(--muted)}.removed-label,.added-label{display:inline-block;padding:2px 7px;border-radius:999px;font:11px/1.4 Inter,sans-serif}.removed-label{border:1px solid #f8514966;color:var(--red)}.added-label{border:1px solid #23863688;color:var(--green)}.gap td{text-align:center;background:var(--head);color:var(--muted)}pre.code{padding:16px;margin:0;overflow:auto;font:13px/1.5 Consolas,monospace;white-space:pre}.tree{padding:16px 20px;overflow:auto}.tree ul{list-style:none;margin:0;padding:0}.tree ul ul{padding-left:24px}.tree li{padding:4px 0}.tree-row{display:inline-flex;align-items:center;gap:10px;min-width:420px}.badge{padding:3px 9px;border:1px solid var(--border);border-radius:999px;font-size:11px;font-weight:600}.changed{color:var(--green);background:#23863633}.unchanged{color:var(--muted);background:#30363d55}.tree li.hidden{display:none}.search{min-width:240px;flex:1}.report-list{list-style:none;margin:0;padding:0}.report-item{display:grid;grid-template-columns:60px 1fr auto;gap:16px;padding:12px 16px;border-bottom:1px solid var(--border)}@media(max-width:700px){body{padding:12px}.banner-meta{grid-template-columns:1fr}.report-item{grid-template-columns:1fr}}
"""


def report_banner():
    return f'<section class="banner"><div class="banner-title">{html.escape(PROGRAM_NAME)}</div><div class="banner-meta"><div><span>Version</span><strong>{html.escape(PROGRAM_VERSION)}</strong></div><div><span>Author</span><strong>{html.escape(PROGRAM_AUTHOR)}</strong></div><div><span>GitHub</span><a href="{html.escape(PROGRAM_GITHUB, quote=True)}">{html.escape(PROGRAM_GITHUB)}</a></div></div></section>'


def full_compare(original, cleaned):
    old, new, result = original.splitlines(), cleaned.splitlines(), []
    for index in range(max(len(old), len(new))):
        before = old[index] if index < len(old) else None
        after = new[index] if index < len(new) else None
        result.append((index + 1, before, after, before != after))
    return result


def diff_table(items, context=False):
    if context:
        indexes = set()
        for index, item in enumerate(items):
            if item[3]: indexes.update(range(max(0, index - DIFF_CONTEXT_LINES), min(len(items), index + DIFF_CONTEXT_LINES + 1)))
        selected = sorted(indexes)
    else:
        selected = [index for index, item in enumerate(items) if item[3]]
    width = max(4, len(str(max((item[0] for item in items), default=1))) + 2)
    rows, previous = [], None
    for index in selected:
        number, before, after, changed = items[index]
        if context and previous is not None and index > previous + 1: rows.append('<tr class="gap"><td colspan="4">...</td></tr>')
        before_html = "" if before is None else html.escape(before)
        after_html = "" if after is None else html.escape(after)
        removed_only = changed and before not in (None, "") and (after is None or after.strip() == "")
        added_only = changed and (before is None or before.strip() == "") and after not in (None, "")
        old_class = "old" if changed and not added_only else "same"
        new_class = "new" if changed and not removed_only else "same"
        old_content = '<span class="added-label">Added</span>' if added_only else (before_html or "&nbsp;")
        new_content = '<span class="removed-label">Removed</span>' if removed_only else (after_html or "&nbsp;")
        rows.append(f'<tr><td class="num {old_class}{" empty-side" if added_only else ""}">{number if before is not None else ""}</td><td class="codecell {old_class}{" empty-side" if added_only else ""}">{old_content}</td><td class="num {new_class}{" empty-side" if removed_only else ""}">{number}</td><td class="codecell {new_class}{" empty-side" if removed_only else ""}">{new_content}</td></tr>')
        previous = index
    return f'<div class="wrap"><table class="diff" style="--line-width:{width}ch"><thead><tr><th colspan="2">Original</th><th colspan="2">Cleaned</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


VIEW_SCRIPT = """<script>(()=>{const b=[...document.querySelectorAll('[data-view]')],c=document.querySelector('#changes'),s=document.querySelector('#context');function set(v){c.classList.toggle('active',v==='changes');s.classList.toggle('active',v==='context');b.forEach(x=>x.classList.toggle('active',x.dataset.view===v));}b.forEach(x=>x.onclick=()=>set(x.dataset.view));set('changes');})();</script>"""


def make_report(path, original, cleaned, output, root, encoding):
    relative = os.path.relpath(path, root); report_relative = relative + ".html"
    target = os.path.join(output, report_relative); os.makedirs(os.path.dirname(target), exist_ok=True)
    items = full_compare(original, cleaned)
    changed = sum(item[3] for item in items)
    removed = sum(item[3] and item[1] not in (None, "") for item in items)
    added = sum(item[3] and item[2] not in (None, "") for item in items)
    parent = os.path.dirname(report_relative.replace("\\", "/")); back = "../" * len([x for x in parent.split("/") if x]) + "index.html"
    size = max(len(original.encode("utf-8")), len(cleaned.encode("utf-8")))
    if size <= MAX_FULL_SOURCE_BYTES:
        sources = f'<section class="section"><h2 class="section-title">Original file</h2><pre class="code">{html.escape(original)}</pre></section><section class="section"><h2 class="section-title">Cleaned file</h2><pre class="code">{html.escape(cleaned)}</pre></section>'
    else:
        sources = f'<section class="section"><h2 class="section-title">Sources omitted</h2><div class="metadata">File exceeds {MAX_FULL_SOURCE_BYTES:,} bytes.</div></section>'
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Diff - {html.escape(relative)}</title><style>{CSS}</style></head><body><main>{report_banner()}<div class="navigation"><a href="{html.escape(back, quote=True)}">&larr; Back to overview</a></div><h1>{html.escape(relative)}</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Changed positions:</span><span>{changed}</span></div><div class="metadata-row"><span class="metadata-label">Removed lines:</span><span class="red">{removed}</span></div><div class="metadata-row"><span class="metadata-label">Added lines:</span><span class="green">{added}</span></div><div class="metadata-row"><span class="metadata-label">Source encoding:</span><span>{html.escape(encoding)}</span></div><div class="metadata-row"><span class="metadata-label">Diff engine:</span><span>Linear positional comparison</span></div></div><section class="section"><h2 class="section-title">Git-style diff</h2><div class="controls"><button class="active" data-view="changes">Only changes</button><button data-view="context">Side-by-side context</button><span class="note">Long lines remain on one row; use horizontal scrolling.</span></div><div class="view active" id="changes">{diff_table(items)}</div><div class="view" id="context">{diff_table(items, True)}</div></section>{sources}{VIEW_SCRIPT}</main></body></html>'''
    with open(target, "w", encoding="utf-8", newline="") as file: file.write(document)
    return report_relative, added, removed


def tree_html(root):
    reports = {os.path.normpath(item["source"]): item for item in debug_reports}
    def render(path):
        try: entries = sorted(os.scandir(path), key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.lower()))
        except OSError: return "<ul></ul>"
        rows = []
        for entry in entries:
            name = html.escape(entry.name); relative = os.path.normpath(os.path.relpath(entry.path, root))
            if entry.is_dir(follow_symlinks=False):
                rows.append(f'<li><details open><summary><span class="tree-row">📁 <span>{name}/</span></span></summary>{render(entry.path)}</details></li>')
            else:
                report = reports.get(relative)
                if report:
                    url = html.escape(report["report"].replace("\\", "/"), quote=True)
                    status = f'<span class="badge changed">Changed</span><span class="muted">-{report["removed"]} / +{report["added"]}</span><a href="{url}">View diff</a>'
                else: status = '<span class="badge unchanged">No changes</span>'
                rows.append(f'<li><span class="tree-row">📄 <span>{name}</span>{status}</span></li>')
        return "<ul>" + "".join(rows) + "</ul>"
    name = html.escape(os.path.basename(root.rstrip(os.sep)) or root)
    return f'<div class="tree"><ul><li><details open><summary><span class="tree-row">📁 <span>{name}/</span><span class="badge changed">{len(reports)} changed</span></span></summary>{render(root)}</details></li></ul></div>'


TREE_SCRIPT = """<script>(()=>{const t=document.querySelector('.tree'),bs=[...document.querySelectorAll('[data-filter]')],q=document.querySelector('#search'),out=document.querySelector('#count');let f='changed';function row(li){const d=[...li.children].find(x=>x.tagName==='DETAILS');return d?d.querySelector(':scope>summary .tree-row'):[...li.children].find(x=>x.classList&&x.classList.contains('tree-row'));}function file(li){const r=row(li);return r&&!li.querySelector(':scope>details');}function visit(li,s){if(file(li)){const r=row(li),changed=!!r.querySelector('.changed'),name=r.textContent.toLowerCase(),show=(f==='all'||(f==='changed'&&changed)||(f==='unchanged'&&!changed))&&(!s||name.includes(s));li.classList.toggle('hidden',!show);return show?1:0;}let n=0,ul=li.querySelector(':scope>details>ul');if(ul)[...ul.children].forEach(x=>n+=visit(x,s));li.classList.toggle('hidden',n===0);return n;}function apply(){let n=0,s=q.value.toLowerCase(),ul=t.querySelector(':scope>ul');[...ul.children].forEach(x=>n+=visit(x,s));out.textContent=n+' matching files';}bs.forEach(b=>b.onclick=()=>{f=b.dataset.filter;bs.forEach(x=>x.classList.toggle('active',x===b));apply();});q.oninput=apply;apply();})();</script>"""


def write_index(diff_dir, root, size_before=None, size_after=None):
    reports = sorted(debug_reports, key=lambda item: item["source"].lower())
    removed, added = sum(item["removed"] for item in reports), sum(item["added"] for item in reports)
    listing = "".join(f'<li class="report-item"><span class="muted">#{index}</span><a href="{html.escape(item["report"].replace(chr(92), "/"), quote=True)}">{html.escape(item["source"])}</a><span><span class="red">-{item["removed"]}</span> / <span class="green">+{item["added"]}</span> · {html.escape(item["encoding"])}</span></li>' for index, item in enumerate(reports, 1))
    filters = '<div class="filter-bar"><button data-filter="all">All files</button><button class="active" data-filter="changed">Changed only</button><button data-filter="unchanged">Unchanged only</button><input class="search" id="search" placeholder="Search files and folders..."><span class="note" id="count"></span></div>'
    size_card = ""
    if size_before:
        percent = (size_before - size_after) / size_before * 100
        size_card = f'<div class="card">Size reduction<span class="value green">-{percent:.1f}%</span></div>'
    loc_before_bucket, loc_after_bucket = loc_stats["before"], loc_stats["after"]
    loc_card = ""
    loc_summary_section = ""
    loc_type_section = ""
    if loc_before_bucket["total"]:
        code_before, code_after = loc_before_bucket["code"], loc_after_bucket["code"]
        code_percent = ((code_before - code_after) / code_before * 100) if code_before else 0.0
        loc_card = f'<div class="card">Code LoC reduction<span class="value green">-{code_percent:.1f}%</span></div>'

        def loc_pct(before, after):
            if before == 0: return 0.0
            return (before - after) / before * 100

        def loc_sign(before, after):
            if after < before: return "-"
            if after > before: return "+"
            return ""

        summary_rows = "".join(
            f'<li class="report-item"><span class="muted">{html.escape(label)}</span>'
            f'<span>{before:,} &rarr; {after:,}</span>'
            f'<span class="{"red" if after > before else "green"}">{loc_sign(before, after)}{abs(loc_pct(before, after)):.1f}%</span></li>'
            for label, before, after in loc_summary_rows(loc_before_bucket, loc_after_bucket)
        )
        loc_summary_section = f'<section class="section"><h2 class="section-title">Lines of code</h2><ul class="report-list">{summary_rows}</ul></section>'

        type_rows = "".join(
            f'<li class="report-item"><span class="muted">{html.escape(ext)}</span>'
            f'<span>Code {b["code"]:,}&rarr;{a["code"]:,} &middot; Comment {b["comment"]:,}&rarr;{a["comment"]:,} &middot; '
            f'Blank {b["blank"]:,}&rarr;{a["blank"]:,} &middot; Total {b["total"]:,}&rarr;{a["total"]:,}</span>'
            f'<span class="{"red" if a["total"] > b["total"] else "green"}">{loc_sign(b["total"], a["total"])}{abs(loc_pct(b["total"], a["total"])):.1f}%</span></li>'
            for ext, b, a in ((ext, entry["before"], entry["after"]) for ext, entry in sorted(loc_by_extension.items()))
        )
        loc_type_section = f'<section class="section"><h2 class="section-title">Lines of code by file type</h2><ul class="report-list">{type_rows}</ul></section>'
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CommentRemover reports</title><style>{CSS}</style></head><body><main>{report_banner()}<h1>CommentRemover Debug Reports</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Project:</span><span>{html.escape(root)}</span></div><div class="metadata-row"><span class="metadata-label">Generated:</span><span>{datetime.now():%Y-%m-%d %H:%M:%S}</span></div></div><div class="summary"><div class="card">Modified files<span class="value">{len(reports)}</span></div><div class="card">Removed lines<span class="value red">{removed}</span></div><div class="card">Added lines<span class="value green">{added}</span></div>{size_card}{loc_card}</div><section class="section"><h2 class="section-title">Directory structure and change status</h2>{filters}{tree_html(root)}</section><section class="section"><h2 class="section-title">Changed files</h2><ul class="report-list">{listing}</ul></section>{loc_summary_section}{loc_type_section}{TREE_SCRIPT}</main></body></html>'''
    with open(os.path.join(diff_dir, "index.html"), "w", encoding="utf-8", newline="") as file: file.write(document)


def process_file(path, debug, diff_dir, root, blank_lines="keep", verify=False):
    if os.path.islink(path): return  # never follow symlinks - copytree(symlinks=True) can point outside the copy
    filename = os.path.basename(path).lower()
    ext_key = "Dockerfile" if filename == "dockerfile" else os.path.splitext(filename)[1].lower()
    handler = remove_hash_comments if filename == "dockerfile" else HANDLERS.get(ext_key)
    if handler is None: return
    try: original, encoding, newline, _ = decode_source_file(path)
    except (OSError, UnicodeError) as error:
        print(f"WARNING: Could not decode: {path}\n         {error}"); return
    handler_output = handler(original)  # line-position-preserving, before optional blank-line collapsing
    cleaned_text = collapse_blank_lines(handler_output, blank_lines)
    cleaned = apply_newline_style(restore_eof(original, cleaned_text), newline)

    # Classify lines as blank/comment/code, both for the original file and for what
    # actually ends up on disk (re-running the handler on the cleaned text is a cheap
    # way to symmetrically detect any comment-like construct the handler intentionally
    # preserves, e.g. a shebang line, so "after" isn't just naively assumed to be zero).
    before_bucket = classify_lines(original, handler_output)
    after_bucket = classify_lines(cleaned, handler(cleaned))
    add_loc_bucket(loc_stats["before"], before_bucket)
    add_loc_bucket(loc_stats["after"], after_bucket)
    ext_bucket = loc_by_extension.setdefault(ext_key, {"before": new_loc_bucket(), "after": new_loc_bucket()})
    add_loc_bucket(ext_bucket["before"], before_bucket)
    add_loc_bucket(ext_bucket["after"], after_bucket)

    if original == cleaned: return

    if verify:
        verifier = VERIFIERS.get(ext_key)
        if verifier is not None:
            ok, message = verifier(cleaned)
            if ok is False:
                print(f"VERIFY FAILED, Original beibehalten: {path}\n  {message.splitlines()[0] if message else ''}")
                changes.append(("VERIFY-FAILED", path)); verify_stats["failed"] += 1
                return
            elif ok is True:
                verify_stats["passed"] += 1
            else:
                verify_stats["unavailable"].add(ext_key)
        else:
            verify_stats["no_verifier"].add(ext_key)

    report, added, removed = (None, 0, 0)
    if debug: report, added, removed = make_report(path, original, cleaned, diff_dir, root, encoding)
    with open(path, "wb") as file: file.write(encode_source_text(cleaned, encoding))
    changes.append(("CLEANED", path))
    if report: debug_reports.append({"source": os.path.relpath(path, root), "report": report, "added": added, "removed": removed, "encoding": encoding})


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    print(console_banner()); print()
    parser = argparse.ArgumentParser(
        prog="CommentRemover.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Creates a copy of a project (timestamped by default, or a custom name via -o) with "
            "comments stripped from its source files. The original project is left untouched unless "
            "--in-place is explicitly used. Optionally deletes non-program assets from the result "
            "and/or writes a browsable HTML diff report."
        ),
        epilog=textwrap.dedent("""\
            examples:
              Clean a project, leave everything else untouched:
                %(prog)s -p ./myproject

              Also write a browsable HTML diff report next to the copy:
                %(prog)s -p ./myproject --debug-diff

              Clean and delete the built-in ballast types (images, archives, docs, ...):
                %(prog)s -p ./myproject -d

              Clean and delete ONLY these extensions, ignore the built-in list:
                %(prog)s -p ./myproject -d --del-include .png .jpg .zip

              Clean and keep ONLY these extensions, delete everything else:
                %(prog)s -p ./myproject -d --del-exclude .py .js .ts

              Also collapse blank lines left behind by removed comments:
                %(prog)s -p ./myproject --blank-lines squeeze

              Use a custom name/location for the copy instead of the timestamped default:
                %(prog)s -p ./myproject -o ./myproject-clean

              Skip the copy entirely and clean the files directly in place (destructive):
                %(prog)s -p ./myproject --in-place

            supported languages (150+ extensions - run with --version or see
            HANDLERS/GENERIC_CONFIGS in the source for the full extension list):
              Python, Shell/Bash/Fish/Zsh, TOML, Ruby, Terraform, R, YAML,
              INI/CFG/Properties, C/C++/C#/Go/CSS/SCSS/LESS/GLSL/HLSL,
              Swift/Kotlin/Rust/Odin/Chapel (nested block comments), Java/Groovy,
              JavaScript/TypeScript/ActionScript (incl. JSX/TSX), Dart, Ada, VBA/
              VB.NET/classic BASIC, Julia, PHP, SQL, HTML/XML/XAML/SVG/Svelte
              (template only), Lua, Dockerfile, MATLAB, Perl, PowerShell, Delphi/
              Object Pascal/Pascal, Modula-2, Fortran (free + fixed form), COBOL
              (free format), OCaml, Racket/Scheme/Common Lisp, Clojure, F#,
              Crystal, Nim, Zig, Verilog/SystemVerilog, VHDL, CoffeeScript,
              ColdFusion (tags only), Tcl, Elm, PureScript, Idris, Agda,
              Handlebars, Liquid, SAS, Wolfram Language, GAMS, Smalltalk, PL/I,
              Forth, Standard ML, x86 Assembly, Logo, ABAP, Red, Io, Factor, J,
              APL, Sed, Stata, Vyper, Solidity, Move, Cairo, X10, Carbon,
              Ballerina, ReScript, Apex (trigger files only)

            Rust uses a hand-written, priority-ordered regex tokenizer for
            higher-precision handling (raw strings r"..."/r#"..."#, and
            lifetimes vs. char literals) - no extra dependency required.
            Every language in this tool needs no extra dependency.

            NOT auto-mapped (see source comments for why): LabVIEW, Ladder
            Logic (graphical), K/Q-kdb+ (ambiguous comment/operator syntax),
            fixed-format COBOL/RPG/Algol/Simula (dialect-specific column
            rules), Prolog and Coq (extensions .pl/.v already claimed by the
            more common Perl/Verilog).
        """),
    )
    parser.add_argument("-p", "--path", "-path", required=True, dest="path", metavar="DIR",
                         help="Path to the project directory to clean. By default a timestamped copy is created next to it; the original is never modified.")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("-o", "--output", dest="output", metavar="DIR", default=None,
                               help="Custom destination directory for the cleaned copy, instead of the default "
                                    "PATH_Clean_TIMESTAMP name (e.g. myproject_Clean_2026-01-02_03-04-05). "
                                    "Must not already exist. Ignored with --in-place.")
    target_group.add_argument("--in-place", action="store_true", dest="in_place",
                               help="DESTRUCTIVE: skip creating a copy entirely and clean the files directly inside "
                                    "--path. The original project is modified. Combine with -d and you can permanently "
                                    "delete files from it too. Use with care, ideally on a project already under version control.")
    parser.add_argument("--debug-diff", action="store_true",
                         help="Write a browsable HTML diff report (index + per-file diffs) alongside the cleaned copy.")
    parser.add_argument("--blank-lines", choices=("keep", "squeeze", "drop"), default="keep", dest="blank_lines",
                         help="How to handle blank lines left behind by comment removal: 'keep' (default) leaves them as-is, "
                              "'squeeze' collapses runs of 2+ blank lines into one, 'drop' removes all blank lines.")
    parser.add_argument("--no-progress", action="store_true", dest="no_progress",
                         help="Disable the live per-file progress indicator (useful for CI logs or piping output to a file).")
    parser.add_argument("--verify", action="store_true", dest="verify",
                         help="After stripping comments from a file, re-check the result with that language's REAL syntax "
                              "checker if one is found on this system (python3/ast, node --check, gcc/g++ -fsyntax-only, "
                              "bash -n, perl -c, php -l, ruby -c, luac -p, gofmt -e). A file that fails this check is left "
                              "UNTOUCHED (original kept) instead of being overwritten. Languages without a wired-up checker "
                              "are cleaned as usual but reported as 'not verified' in the summary - review those manually.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")

    delete_options = parser.add_argument_group(
        "deletion options",
        "Control removal of non-program assets from the copy. Only takes effect together with -d/--delete.",
    )
    delete_options.add_argument("-d", "--delete", action="store_true",
                                 help="After cleaning, also delete non-program assets from the copy (see below for which ones).")
    del_group = delete_options.add_mutually_exclusive_group()
    del_group.add_argument("--del-include", nargs="+", default=None, dest="del_include", metavar="EXT",
                            help="Replace the built-in delete list entirely: delete ONLY files with these extensions, "
                                 "e.g. --del-include .png .jpg .zip")
    del_group.add_argument("--del-exclude", nargs="+", default=None, dest="del_exclude", metavar="EXT",
                            help="Invert the built-in delete list: delete every file whose extension is NOT listed here "
                                 "('keep-only' mode), e.g. --del-exclude .py .js .ts keeps only Python/JS/TS files. "
                                 "Extensionless files (Dockerfile, LICENSE, Makefile, .gitignore, ...) are always kept.")

    args = parser.parse_args()
    if (args.del_include or args.del_exclude) and not args.delete:
        print("WARNING: --del-include/--del-exclude have no effect without -d/--delete.\n")
    source = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(source): print("ERROR: Invalid directory:", source); return 1

    if args.in_place:
        destination = source
        warning = "WARNING: --in-place is active - no copy is made, files are modified directly in the source directory."
        if args.delete: warning += "\nWARNING: combined with -d/--delete, matching files will be permanently removed from the source directory."
        print(warning + "\n")
    else:
        if args.output:
            destination = os.path.abspath(os.path.expanduser(args.output))
            if os.path.exists(destination): print("ERROR: Output directory already exists:", destination); return 1
        else:
            destination = source.rstrip("\\/") + datetime.now().strftime("_Clean_%Y-%m-%d_%H-%M-%S")
        print("Copying project..."); shutil.copytree(source, destination, symlinks=True)

    diff_dir = destination + "_DEBUG-FILE" if args.debug_diff else None
    if diff_dir: os.makedirs(diff_dir, exist_ok=True)

    all_files = [os.path.join(current, name) for current, _, files in os.walk(destination) for name in files]
    total_size_before = sum(safe_size(path) for path in all_files)
    total_files = len(all_files)
    show_progress = not args.no_progress and total_files > 0

    print("Removing comments...")
    for index, path in enumerate(all_files, 1):
        if show_progress:
            label = f"[{index}/{total_files}] {os.path.relpath(path, destination)}"
            print("\r" + label.ljust(100)[:100], end="", flush=True)
        process_file(path, args.debug_diff, diff_dir, destination, args.blank_lines, verify=args.verify)
    if show_progress: print()

    if args.delete:
        print("Deleting selected non-program assets...")
        if args.del_include:
            delete_types = normalize_extensions(args.del_include)
            should_delete = lambda ext: ext in delete_types
        elif args.del_exclude:
            keep_types = normalize_extensions(args.del_exclude)
            should_delete = lambda ext: ext != "" and ext not in keep_types
        else:
            delete_types = set(DELETE_TYPES)
            should_delete = lambda ext: ext in delete_types
        for current, directories, files in os.walk(destination):
            directories[:] = [name for name in directories if name != ".git"]
            for name in files:
                path = os.path.join(current, name)
                if should_delete(os.path.splitext(name)[1].lower()):
                    os.remove(path); changes.append(("REMOVED", path))

    total_size_after = sum(safe_size(os.path.join(dp, f)) for dp, _, fs in os.walk(destination) for f in fs)
    reduction = total_size_before - total_size_after
    percent = (reduction / total_size_before * 100) if total_size_before else 0.0

    if diff_dir: write_index(diff_dir, destination, total_size_before, total_size_after)
    print("\nModified project (in place):" if args.in_place else "\nCopy-Project:"); print(destination)
    if diff_dir: print("\nHTML report:"); print(os.path.join(diff_dir, "index.html"))
    print("")
    print("-------------------------------------------------------------")
    print("")
    for action, path in changes: print(f"{action:8}: {os.path.relpath(path, destination)}")
    print("")
    print("-------------------------------------------------------------")
    print("")
    print(f"Changes: {len(changes)}")
    print(f"Project size: {total_size_before:,} -> {total_size_after:,} bytes (-{percent:.1f}%, -{reduction:,} bytes)")

    print("\nLines of code:")
    summary_rows = loc_summary_rows(loc_stats["before"], loc_stats["after"])
    label_width = max(len(label) for label, _, _ in summary_rows)
    for label, before, after in summary_rows:
        print(f"  {label.ljust(label_width)} : {format_loc_change(before, after)}")

    print_loc_by_type_table(loc_by_extension)

    if args.verify:
        print("\nVerification (--verify):")
        print(f"  Bestanden: {verify_stats['passed']}")
        print(f"  FEHLGESCHLAGEN (Original beibehalten): {verify_stats['failed']}")
        if verify_stats["unavailable"]:
            print(f"  Kein Checker auf diesem System installiert für: {', '.join(sorted(verify_stats['unavailable']))}")
        if verify_stats["no_verifier"]:
            print(f"  Kein Verifier implementiert für: {', '.join(sorted(verify_stats['no_verifier']))} - bitte manuell prüfen (--debug-diff empfohlen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

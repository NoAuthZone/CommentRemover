#!/usr/bin/env python3
"""Create a cleaned project copy and optional scalable HTML diff reports."""

import argparse
import html
import os
import re
import shutil
from datetime import datetime

PROGRAM_NAME = "CommentRemover"
PROGRAM_VERSION = "2.0"
PROGRAM_AUTHOR = "NoAuthZone"
PROGRAM_GITHUB = "https://github.com/NoAuthZone/CommentRemover"
DIFF_CONTEXT_LINES = 5
MAX_FULL_SOURCE_BYTES = 1_000_000

changes = []
debug_reports = []
deleted_files = []


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


def scan_hash_line(line, preserve_hex_colors=False):
    output, quote, escaped, index = [], None, False, 0
    while index < len(line):
        char = line[index]
        if escaped:
            output.append(char); escaped = False; index += 1; continue
        if char == "\\" and quote is not None:
            output.append(char); escaped = True; index += 1; continue
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
    return "".join(output).rstrip()


def remove_hash_comments(text):
    lines = []
    for number, line in enumerate(text.splitlines()):
        lines.append(line if number == 0 and line.startswith("#!") else scan_hash_line(line))
    return restore_eof(text, "\n".join(lines))


def remove_config_hash_comments(text):
    return restore_eof(text, "\n".join(scan_hash_line(line, True) for line in text.splitlines()))


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
# Handlers
# ---------------------------------------------------------------------------

HANDLERS = {}
for ext in (".py", ".sh", ".toml", ".rb", ".tf"): HANDLERS[ext] = remove_hash_comments
for ext in (".yml", ".yaml"): HANDLERS[ext] = remove_yaml_comments
for ext in (".ini", ".cfg", ".conf", ".properties"): HANDLERS[ext] = remove_config_hash_comments
for ext in (".cs", ".c", ".cpp", ".cc", ".h", ".hpp", ".go", ".swift", ".kt", ".kts", ".css", ".scss", ".less", ".rs"): HANDLERS[ext] = remove_c_comments
HANDLERS[".java"] = remove_java_comments
for ext in (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts"): HANDLERS[ext] = remove_javascript_comments
for ext in (".jsx", ".tsx"): HANDLERS[ext] = remove_jsx_comments
HANDLERS.update({".html": remove_xml_comments, ".htm": remove_xml_comments, ".php": remove_php_comments, ".sql": remove_sql_comments, ".xml": remove_xml_comments, ".xaml": remove_xml_comments, ".svg": remove_xml_comments, ".lua": remove_lua_comments})

DELETE_TYPES = {".md", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".mp3", ".mp4", ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".rar", ".7z", ".gz", ".pyc", ".class", ".jar"}


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


def write_index(diff_dir, root):
    reports = sorted(debug_reports, key=lambda item: item["source"].lower())
    removed, added = sum(item["removed"] for item in reports), sum(item["added"] for item in reports)
    listing = "".join(f'<li class="report-item"><span class="muted">#{index}</span><a href="{html.escape(item["report"].replace(chr(92), "/"), quote=True)}">{html.escape(item["source"])}</a><span><span class="red">-{item["removed"]}</span> / <span class="green">+{item["added"]}</span> · {html.escape(item["encoding"])}</span></li>' for index, item in enumerate(reports, 1))
    filters = '<div class="filter-bar"><button data-filter="all">All files</button><button class="active" data-filter="changed">Changed only</button><button data-filter="unchanged">Unchanged only</button><input class="search" id="search" placeholder="Search files and folders..."><span class="note" id="count"></span></div>'
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CommentRemover reports</title><style>{CSS}</style></head><body><main>{report_banner()}<h1>CommentRemover Debug Reports</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Project:</span><span>{html.escape(root)}</span></div><div class="metadata-row"><span class="metadata-label">Generated:</span><span>{datetime.now():%Y-%m-%d %H:%M:%S}</span></div></div><div class="summary"><div class="card">Modified files<span class="value">{len(reports)}</span></div><div class="card">Removed lines<span class="value red">{removed}</span></div><div class="card">Added lines<span class="value green">{added}</span></div></div><section class="section"><h2 class="section-title">Directory structure and change status</h2>{filters}{tree_html(root)}</section><section class="section"><h2 class="section-title">Changed files</h2><ul class="report-list">{listing}</ul></section>{TREE_SCRIPT}</main></body></html>'''
    with open(os.path.join(diff_dir, "index.html"), "w", encoding="utf-8", newline="") as file: file.write(document)


def process_file(path, debug, diff_dir, root):
    filename = os.path.basename(path).lower()
    handler = remove_hash_comments if filename == "dockerfile" else HANDLERS.get(os.path.splitext(filename)[1].lower())
    if handler is None: return
    try: original, encoding, newline, _ = decode_source_file(path)
    except (OSError, UnicodeError) as error:
        print(f"WARNING: Could not decode: {path}\n         {error}"); return
    cleaned = apply_newline_style(restore_eof(original, handler(original)), newline)
    if original == cleaned: return
    report, added, removed = (None, 0, 0)
    if debug: report, added, removed = make_report(path, original, cleaned, diff_dir, root, encoding)
    with open(path, "wb") as file: file.write(encode_source_text(cleaned, encoding))
    changes.append(("CLEANED", path))
    if report: debug_reports.append({"source": os.path.relpath(path, root), "report": report, "added": added, "removed": removed, "encoding": encoding})


def main():
    print(console_banner()); print()
    parser = argparse.ArgumentParser(prog="CommentRemover.py")
    parser.add_argument("-p", "--path", "-path", required=True, dest="path")
    parser.add_argument("--debug-diff", action="store_true")
    parser.add_argument("-d", "--delete", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")
    args = parser.parse_args()
    source = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(source): print("ERROR: Invalid directory:", source); return 1
    destination = source.rstrip("\\/") + datetime.now().strftime("_Clean_%Y-%m-%d_%H-%M-%S")
    diff_dir = destination + "_DEBUG-FILE" if args.debug_diff else None
    print("Copying project..."); shutil.copytree(source, destination, symlinks=True)
    if diff_dir: os.makedirs(diff_dir)
    print("Removing comments...")
    for current, directories, files in os.walk(destination):
        for name in files: process_file(os.path.join(current, name), args.debug_diff, diff_dir, destination)
    if args.delete:
        print("Deleting selected non-program assets...")
        for current, directories, files in os.walk(destination):
            directories[:] = [name for name in directories if name != ".git"]
            for name in files:
                path = os.path.join(current, name)
                if os.path.splitext(name)[1].lower() in DELETE_TYPES:
                    os.remove(path); changes.append(("REMOVED", path))
    if diff_dir: write_index(diff_dir, destination)
    print("\nCopy-Project:"); print(destination)
    if diff_dir: print("\nHTML report:"); print(os.path.join(diff_dir, "index.html"))
    print("")
    print("-------------------------------------------------------------")
    print("")
    for action, path in changes: print(f"{action:8}: {os.path.relpath(path, destination)}")
    print("")
    print("-------------------------------------------------------------")
    print("")
    print(f"Changes: {len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

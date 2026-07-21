#!/usr/bin/env python3
"""Create a code-only project copy and optional, scalable HTML diff reports."""

import argparse
import html
import os
import re
import shutil
from datetime import datetime

PROGRAM_NAME = "CommentRemover"
PROGRAM_VERSION = "1.3"
PROGRAM_AUTHOR = "NoAuthZone"
PROGRAM_GITHUB = "https://github.com/NoAuthZone/CommentRemover"

# Report limits keep memory usage manageable for large projects/files.
DIFF_CONTEXT_LINES = 5
MAX_SIDE_BY_SIDE_LINES = 25_000
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


def html_banner():
    return f'''<section class="program-banner">
<div class="program-title">{html.escape(PROGRAM_NAME)}</div>
<div class="program-meta">
<div><span>Version</span><strong>{html.escape(PROGRAM_VERSION)}</strong></div>
<div><span>Author</span><strong>{html.escape(PROGRAM_AUTHOR)}</strong></div>
<div><span>GitHub</span><a href="{html.escape(PROGRAM_GITHUB, quote=True)}">{html.escape(PROGRAM_GITHUB)}</a></div>
</div></section>'''


def restore_eof(original, cleaned):
    if original.endswith("\n") and not cleaned.endswith("\n"):
        return cleaned + "\n"
    if not original.endswith("\n") and cleaned.endswith("\n"):
        return cleaned.rstrip("\r\n")
    return cleaned


def preserve_newlines(match):
    return "".join(char for char in match.group(0) if char in "\r\n")


def scan_hash_line(line, preserve_hex_colors=False):
    """Remove an unquoted # comment; optionally preserve CSS-style hex colors."""
    output = []
    quote = None
    escaped = False
    index = 0

    while index < len(line):
        char = line[index]

        if escaped:
            output.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\" and quote is not None:
            output.append(char)
            escaped = True
            index += 1
            continue

        if char in ('"', "'"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            output.append(char)
            index += 1
            continue

        if char == "#" and quote is None:
            if preserve_hex_colors:
                match = re.match(r"#[0-9A-Fa-f]{3,8}(?![0-9A-Fa-f])", line[index:])
                before = line[:index].rstrip()
                if match and before.endswith(("=", ":", "(", ",")):
                    output.append(match.group(0))
                    index += len(match.group(0))
                    continue
            break

        output.append(char)
        index += 1

    return "".join(output).rstrip()


def remove_hash_comments(text):
    lines = []
    for number, line in enumerate(text.splitlines()):
        if number == 0 and line.startswith("#!"):
            lines.append(line)
        else:
            lines.append(scan_hash_line(line))
    return restore_eof(text, "\n".join(lines))


def remove_config_hash_comments(text):
    """Preserve #RGB/#RGBA/#RRGGBB/#RRGGBBAA values in INI-like files."""
    lines = [scan_hash_line(line, preserve_hex_colors=True) for line in text.splitlines()]
    return restore_eof(text, "\n".join(lines))


def remove_c_comments(text):
    output = []
    index = 0
    quote = None
    escaped = False

    while index < len(text):
        char = text[index]
        pair = text[index:index + 2]

        if escaped:
            output.append(char)
            escaped = False
            index += 1
            continue

        if quote is not None:
            output.append(char)
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char in ('"', "'", "`"):
            quote = char
            output.append(char)
            index += 1
            continue

        if pair == "//":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue

        if pair == "/*":
            index += 2
            while index < len(text) - 1 and text[index:index + 2] != "*/":
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            if index < len(text) - 1:
                index += 2
            continue

        output.append(char)
        index += 1

    return restore_eof(text, "".join(output))


def remove_sql_comments(text):
    output = []
    index = 0
    quote = None

    while index < len(text):
        char = text[index]
        pair = text[index:index + 2]

        if quote is not None:
            output.append(char)
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    output.append(quote)
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if char in ('"', "'"):
            quote = char
            output.append(char)
            index += 1
            continue

        if pair == "--" or char == "#":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue

        if pair == "/*":
            index += 2
            while index < len(text) - 1 and text[index:index + 2] != "*/":
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            if index < len(text) - 1:
                index += 2
            continue

        output.append(char)
        index += 1

    return restore_eof(text, "".join(output))


def remove_xml_comments(text):
    cleaned = re.sub(r"<!--.*?-->", preserve_newlines, text, flags=re.DOTALL)
    return restore_eof(text, cleaned)


def remove_lua_comments(text):
    cleaned = re.sub(r"--\[\[.*?\]\]", preserve_newlines, text, flags=re.DOTALL)
    cleaned = re.sub(r"--.*?$", "", cleaned, flags=re.MULTILINE)
    return restore_eof(text, cleaned)


def remove_php_comments(text):
    output = []
    index = 0
    quote = None
    escaped = False

    while index < len(text):
        char = text[index]
        pair = text[index:index + 2]

        if escaped:
            output.append(char)
            escaped = False
            index += 1
            continue

        if quote is not None:
            output.append(char)
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char in ('"', "'"):
            quote = char
            output.append(char)
            index += 1
            continue

        if pair == "//" or char == "#":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue

        if pair == "/*":
            index += 2
            while index < len(text) - 1 and text[index:index + 2] != "*/":
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            if index < len(text) - 1:
                index += 2
            continue

        output.append(char)
        index += 1

    return restore_eof(text, remove_xml_comments("".join(output)))


CSS = '''
:root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--head:#21262d;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--blue:#58a6ff}*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1800px;margin:auto}h1{color:var(--blue)}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.metadata,.navigation,.section,.summary-card,.program-banner{background:var(--panel);border:1px solid var(--border);border-radius:8px}.metadata,.navigation{padding:16px;margin-bottom:24px}.metadata-row{display:flex;gap:12px;margin:5px 0}.metadata-label{min-width:140px;color:var(--muted)}.program-banner{margin-bottom:24px;overflow:hidden}.program-title{padding:16px;text-align:center;font-size:24px;font-weight:700;background:var(--head);border-bottom:1px solid var(--border)}.program-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--border)}.program-meta>div{display:flex;flex-direction:column;gap:5px;padding:13px 16px;background:var(--panel)}.program-meta span{color:var(--muted);font-size:12px}.section{margin-bottom:28px;overflow:hidden}.section-title{padding:12px 16px;margin:0;background:var(--head);border-bottom:1px solid var(--border)}.code{padding:16px;margin:0;overflow:auto;font:13px/1.5 Consolas,"Cascadia Code",monospace;white-space:pre}.notice{padding:18px;color:var(--muted)}.diff-wrapper{overflow:auto}table.diff{width:100%;min-width:900px;border-collapse:collapse;font:12px Consolas,monospace}table.diff td,table.diff th{padding:3px 7px;border:1px solid var(--border);vertical-align:top;white-space:pre-wrap}.diff_header{background:var(--head)}.diff_add{background:#2ea04355}.diff_chg{background:#d2992255}.diff_sub{background:#f8514955}.summary{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}.summary-card{min-width:180px;padding:16px}.summary-value{display:block;margin-top:6px;font-size:28px;font-weight:bold}.status-added{color:#3fb950}.status-removed{color:#f85149}.status-warn{color:#d29922}.report-list,.tree ul{list-style:none;margin:0;padding:0}.report-item{display:grid;grid-template-columns:60px 1fr auto;gap:16px;padding:12px 16px;border-bottom:1px solid var(--border)}.report-number,.muted{color:var(--muted)}.tree{padding:16px 20px;overflow:auto}.tree ul ul{padding-left:24px}.tree li{padding:4px 0}.tree details>summary{cursor:pointer}.tree-row{display:inline-flex;align-items:center;gap:10px;min-width:420px}.tree-name{white-space:normal;overflow-wrap:anywhere}.icon{width:20px}.badge{padding:3px 9px;border:1px solid var(--border);border-radius:999px;font-size:11px;font-weight:600}.changed{color:#3fb950;background:#23863633;border-color:#238636}.folder-changed{color:#d2a8ff;background:#8957e533;border-color:#8957e5}.unchanged{color:var(--muted);background:#30363d55}.tree-stats{color:var(--muted);font-size:11px}.tree-link{font-size:12px}.filter-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border)}.filter-button,.filter-search{padding:8px 12px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:7px;font:inherit}.filter-button{cursor:pointer}.filter-button.active{color:white;background:#1f6feb;border-color:#388bfd}.filter-search{min-width:240px;flex:1}.filter-result{color:var(--muted);font-size:12px}.tree li.filter-hidden{display:none!important}.help-list{padding:16px 34px}.linear-diff{width:100%;border-collapse:collapse;table-layout:auto;font:13px/1.5 Consolas,"Cascadia Code",monospace}.linear-diff th{padding:10px;background:var(--head);border:1px solid var(--border)}.linear-diff td{padding:5px 8px;border:1px solid var(--border);vertical-align:top}.linear-diff .line-number{width:var(--line-number-width,5ch);min-width:var(--line-number-width,5ch);max-width:var(--line-number-width,5ch);padding-left:6px;padding-right:6px;color:var(--muted);text-align:right;white-space:nowrap;user-select:none}.linear-diff .line-code{width:auto;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}.linear-diff .old-line{background:#f8514924}.linear-diff .new-line{background:#2ea04324}.linear-diff .same-line{background:var(--panel)}.linear-diff .separator td{padding:3px;background:var(--head);color:var(--muted);text-align:center}.diff-legend{display:flex;gap:16px;flex-wrap:wrap;padding:10px 16px;color:var(--muted);font-size:12px}.legend-old{color:#ff7b72}.legend-new{color:#3fb950}.diff-view-controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--border)}.diff-view-button{padding:8px 13px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:7px;cursor:pointer;font:inherit}.diff-view-button:hover{border-color:var(--blue)}.diff-view-button.active{color:#fff;background:#1f6feb;border-color:#388bfd}.diff-view-note{color:var(--muted);font-size:12px}.changed-lines-view,.side-by-side-view{display:none}.changed-lines-view.active,.side-by-side-view.active{display:block}.changed-lines-table{width:100%;border-collapse:collapse;table-layout:fixed;font:13px/1.5 Consolas,"Cascadia Code",monospace}.changed-lines-table th{padding:10px 12px;text-align:center;background:var(--head);border:1px solid var(--border)}.changed-lines-table td{padding:6px 10px;border:1px solid var(--border);vertical-align:top}.changed-lines-table .compact-number{width:var(--line-number-width,5ch);min-width:var(--line-number-width,5ch);max-width:var(--line-number-width,5ch);text-align:right;white-space:nowrap;color:var(--muted)}.changed-lines-table .compact-code{width:auto;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}.changed-lines-table .original-number,.changed-lines-table .original-code{background:#3b2024}.changed-lines-table .cleaned-number,.changed-lines-table .cleaned-code{background:#153828}.changed-lines-table .empty-change{color:var(--muted);opacity:.55}.empty-diff{padding:18px;color:var(--muted)}.deleted-list{list-style:none;margin:0;padding:0}.deleted-item{display:grid;grid-template-columns:minmax(260px,1fr) auto auto;gap:14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border)}.deleted-item:last-child{border-bottom:0}.deleted-path{color:#ff7b72;overflow-wrap:anywhere}.deleted-meta{color:var(--muted);font-size:12px;white-space:nowrap}.deleted-badge{padding:3px 9px;color:#ff7b72;background:#f8514924;border:1px solid #f85149;border-radius:999px;font-size:11px;font-weight:700}.badge.deleted{color:#ff7b72;background:#f8514924;border-color:#f85149}.deleted-tree-file .tree-name{color:#ff7b72;text-decoration:line-through}.deleted-tree-meta{color:var(--muted);font-size:11px;white-space:nowrap}.deleted-empty{padding:18px;color:var(--muted)}@media(max-width:700px){.deleted-item{grid-template-columns:1fr}.deleted-meta,.deleted-badge{justify-self:start}}@media(max-width:700px){body{padding:12px}.program-meta{grid-template-columns:1fr}.report-item{grid-template-columns:1fr}.metadata-row{flex-direction:column}}
'''

FILTERS = '''<div class="filter-bar"><button class="filter-button" data-filter="all">All files</button><button class="filter-button active" data-filter="changed">Changed only</button><button class="filter-button" data-filter="unchanged">Unchanged only</button><button class="filter-button" data-filter="deleted">Deleted only</button><input id="tree-search" class="filter-search" type="search" placeholder="Search files and folders..."><span id="filter-result" class="filter-result"></span></div>'''

SCRIPT = r'''<script>(()=>{const tree=document.querySelector('.tree'),buttons=[...document.querySelectorAll('.filter-button')],search=document.querySelector('#tree-search'),result=document.querySelector('#filter-result');if(!tree)return;let filter='changed';function row(li){const d=[...li.children].find(x=>x.tagName==='DETAILS');return d?d.querySelector(':scope>summary .tree-row'):[...li.children].find(x=>x.classList&&x.classList.contains('tree-row'));}function file(li){const r=row(li),i=r&&r.querySelector('.icon');return !!(i&&(i.textContent.includes('📄')||i.textContent.includes('🗑️')));}function status(li){const r=row(li);return r&&r.querySelector('.badge.deleted')?'deleted':(r&&r.querySelector('.badge.changed')?'changed':'unchanged');}function match(li,q){const r=row(li),n=r&&r.querySelector('.tree-name');return !q||!!(n&&n.textContent.toLowerCase().includes(q));}function visit(li,q){if(file(li)){const visible=(filter==='all'||status(li)===filter)&&match(li,q);li.classList.toggle('filter-hidden',!visible);return visible?1:0;}let hits=0;const ul=li.querySelector(':scope>details>ul');if(ul)[...ul.children].forEach(c=>{if(c.tagName==='LI')hits+=visit(c,q)});li.classList.toggle('filter-hidden',hits===0);const d=li.querySelector(':scope>details');if(d&&hits&&(filter!=='all'||q))d.open=true;return hits;}function apply(){let hits=0,q=search.value.trim().toLowerCase(),ul=tree.querySelector(':scope>ul');if(ul)[...ul.children].forEach(c=>hits+=visit(c,q));result.textContent=hits+(hits===1?' matching file':' matching files');}buttons.forEach(b=>b.onclick=()=>{filter=b.dataset.filter;buttons.forEach(x=>x.classList.toggle('active',x===b));apply()});search.oninput=apply;apply();})();</script>'''


def compare_lines(original, cleaned):
    """Compare lines by position in linear time."""
    original_lines = original.splitlines()
    cleaned_lines = cleaned.splitlines()
    line_count = max(len(original_lines), len(cleaned_lines))
    compared = []
    for index in range(line_count):
        old_line = original_lines[index] if index < len(original_lines) else None
        new_line = cleaned_lines[index] if index < len(cleaned_lines) else None
        compared.append({
            "number": index + 1,
            "original": old_line,
            "cleaned": new_line,
            "changed": old_line != new_line,
        })
    return compared


def change_counts(compared):
    removed = 0
    added = 0
    for item in compared:
        if not item["changed"]:
            continue
        if item["original"] not in (None, ""):
            removed += 1
        if item["cleaned"] not in (None, ""):
            added += 1
    return added, removed


def has_change(original, cleaned):
    return original.rstrip("\r\n") != cleaned.rstrip("\r\n")


def back_link(relative):
    parent = os.path.dirname(relative.replace("\\", "/"))
    return "../" * len([part for part in parent.split("/") if part]) + "index.html"


def context_line_numbers(compared, context=DIFF_CONTEXT_LINES):
    selected = set()
    total = len(compared)
    for index, item in enumerate(compared):
        if item["changed"]:
            selected.update(range(max(0, index - context), min(total, index + context + 1)))
    return sorted(selected)



def render_changed_lines(compared):
    """Render changed positions with Original and Cleaned side by side."""
    rows = []
    max_number = max((item["number"] for item in compared), default=1)
    number_width = max(4, len(str(max_number)) + 2)

    for item in compared:
        if not item["changed"]:
            continue

        number = item["number"]
        old_line = item["original"]
        new_line = item["cleaned"]
        old_html = "" if old_line is None else html.escape(old_line)
        new_html = "" if new_line is None else html.escape(new_line)
        old_class = "" if old_line not in (None, "") else " empty-change"
        new_class = "" if new_line not in (None, "") else " empty-change"

        rows.append(
            '<tr class="changed-position-row">'
            f'<td class="compact-number original-number">{number if old_line is not None else ""}</td>'
            f'<td class="compact-code original-code{old_class}">{old_html or "&nbsp;"}</td>'
            f'<td class="compact-number cleaned-number">{number if new_line is not None else ""}</td>'
            f'<td class="compact-code cleaned-code{new_class}">{new_html or "&nbsp;"}</td>'
            '</tr>'
        )

    if not rows:
        return '<div class="empty-diff">No changed positions found.</div>'

    return (
        '<div class="diff-wrapper">'
        f'<table class="changed-lines-table" style="--line-number-width:{number_width}ch">'
        '<colgroup><col class="compact-number"><col class="compact-code">'
        '<col class="compact-number"><col class="compact-code"></colgroup>'
        '<thead><tr><th colspan="2">Original</th><th colspan="2">Cleaned</th></tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody></table></div>'
    )


REPORT_VIEW_SCRIPT = r"""<script>
(function () {
    "use strict";
    const buttons = Array.from(document.querySelectorAll(".diff-view-button"));
    const compact = document.querySelector(".changed-lines-view");
    const sideBySide = document.querySelector(".side-by-side-view");

    function setView(view) {
        const compactActive = view === "changed";
        if (compact) compact.classList.toggle("active", compactActive);
        if (sideBySide) sideBySide.classList.toggle("active", !compactActive);
        buttons.forEach(function (button) {
            button.classList.toggle("active", button.dataset.view === view);
        });
    }

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            setView(button.dataset.view);
        });
    });

    setView("changed");
}());
</script>"""


def render_linear_diff(compared):
    indexes = context_line_numbers(compared)
    rows = []
    previous = None
    for index in indexes:
        item = compared[index]
        if previous is not None and index > previous + 1:
            rows.append('<tr class="separator"><td colspan="4">...</td></tr>')
        number = item["number"]
        old_line = item["original"]
        new_line = item["cleaned"]
        changed = item["changed"]
        old_class = "old-line" if changed else "same-line"
        new_class = "new-line" if changed else "same-line"
        old_html = "" if old_line is None else html.escape(old_line)
        new_html = "" if new_line is None else html.escape(new_line)
        rows.append(
            '<tr>'
            f'<td class="line-number {old_class}">{number if old_line is not None else ""}</td>'
            f'<td class="line-code {old_class}">{old_html or "&nbsp;"}</td>'
            f'<td class="line-number {new_class}">{number if new_line is not None else ""}</td>'
            f'<td class="line-code {new_class}">{new_html or "&nbsp;"}</td>'
            '</tr>'
        )
        previous = index
    if not rows:
        rows.append('<tr><td colspan="4" class="notice">No changed lines found.</td></tr>')
    max_line_number = max((item["number"] for item in compared), default=1)
    line_number_width = max(4, len(str(max_line_number)) + 2)

    return (
        '<div class="diff-wrapper">'
        '<div class="diff-legend"><span class="legend-old">Original / removed</span>'
        '<span class="legend-new">Cleaned / added</span></div>'
        f'<table class="linear-diff" style="--line-number-width:{line_number_width}ch">'
        '<colgroup><col class="line-number-column"><col class="code-column">'
        '<col class="line-number-column"><col class="code-column"></colgroup>'
        '<thead><tr><th colspan="2">Original</th>'
        '<th colspan="2">Cleaned</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></div>'
    )


def make_report(path, original, cleaned, output, root, compared=None):
    relative = os.path.relpath(path, root)
    report_relative = relative + ".html"
    report_path = os.path.join(output, report_relative)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    if compared is None:
        compared = compare_lines(original, cleaned)
    added, removed = change_counts(compared)
    changed_line_count = sum(item["changed"] for item in compared)
    source_bytes = max(len(original.encode("utf-8")), len(cleaned.encode("utf-8")))
    diff_content = render_linear_diff(compared)
    compact_content = render_changed_lines(compared)
    if source_bytes <= MAX_FULL_SOURCE_BYTES:
        sources = (
            '<section class="section"><h2 class="section-title">Original file</h2>'
            f'<pre class="code">{html.escape(original)}</pre></section>'
            '<section class="section"><h2 class="section-title">Cleaned file</h2>'
            f'<pre class="code">{html.escape(cleaned)}</pre></section>'
        )
    else:
        sources = (
            '<section class="section"><h2 class="section-title">Complete source views omitted</h2>'
            f'<div class="notice">The file is larger than {MAX_FULL_SOURCE_BYTES:,} bytes. '
            'Full source views were omitted to keep the report responsive.</div></section>'
        )
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Diff - {html.escape(relative)}</title><style>{CSS}</style></head><body><main>'
        f'{html_banner()}<div class="navigation"><a href="{html.escape(back_link(report_relative), quote=True)}">'
        f'&larr; Back to overview</a></div><h1>{html.escape(relative)}</h1>'
        '<div class="metadata">'
        f'<div class="metadata-row"><span class="metadata-label">Changed positions:</span><span>{changed_line_count}</span></div>'
        f'<div class="metadata-row"><span class="metadata-label">Removed lines:</span><span class="status-removed">{removed}</span></div>'
        f'<div class="metadata-row"><span class="metadata-label">Added lines:</span><span class="status-added">{added}</span></div>'
        '<div class="metadata-row"><span class="metadata-label">Diff engine:</span><span>Linear positional comparison</span></div>'
        f'<div class="metadata-row"><span class="metadata-label">File size:</span><span>{source_bytes:,} bytes</span></div></div>'
        '<section class="section"><h2 class="section-title">Git-style diff</h2>'
        '<div class="diff-view-controls">'
        '<button class="diff-view-button active" type="button" data-view="changed">Only changes</button>'
        '<button class="diff-view-button" type="button" data-view="side">Side-by-side context</button>'
        '<span class="diff-view-note">Shows only changed positions with Original and Cleaned side by side.</span>'
        '</div>'
        f'<div class="changed-lines-view active">{compact_content}</div>'
        f'<div class="side-by-side-view">{diff_content}</div>'
        '</section>'
        f'{sources}{REPORT_VIEW_SCRIPT}</main></body></html>'
    )
    with open(report_path, "w", encoding="utf-8", newline="") as file:
        file.write(document)
    return report_relative


def tree_html(root):
    """Render existing and deleted files in one merged directory tree."""
    reports = {
        os.path.normpath(str(item["source"])): item
        for item in debug_reports
    }

    # Directory nodes contain child directories and file records. Deleted
    # files are inserted at their former path, so no separate Deleted folder
    # is required in the report.
    tree = {
        "directories": {},
        "files": {},
    }

    def directory_node(parts):
        node = tree
        for part in parts:
            node = node["directories"].setdefault(
                part,
                {"directories": {}, "files": {}},
            )
        return node

    # Existing files and directories from the copied project.
    for current, directories, files in os.walk(root):
        relative_directory = os.path.relpath(current, root)
        parts = [] if relative_directory == "." else relative_directory.split(os.sep)
        node = directory_node(parts)

        for directory_name in directories:
            node["directories"].setdefault(
                directory_name,
                {"directories": {}, "files": {}},
            )

        for filename in files:
            relative_path = os.path.normpath(
                os.path.join(relative_directory, filename)
                if relative_directory != "."
                else filename
            )
            node["files"][filename] = {
                "path": relative_path,
                "deleted": False,
            }

    # Deleted files are added back virtually at their original locations.
    for deleted in deleted_files:
        relative_path = os.path.normpath(str(deleted["path"]))
        parts = relative_path.split(os.sep)
        node = directory_node(parts[:-1])
        node["files"][parts[-1]] = {
            "path": relative_path,
            "deleted": True,
            "extension": deleted.get("extension") or "no extension",
            "size": int(deleted.get("size", 0)),
        }

    def subtree_counts(node):
        changed = 0
        deleted = 0

        for file_record in node["files"].values():
            if file_record["deleted"]:
                deleted += 1
            else:
                report = reports.get(file_record["path"])
                if report is not None:
                    changed += 1

        for child in node["directories"].values():
            child_changed, child_deleted = subtree_counts(child)
            changed += child_changed
            deleted += child_deleted

        return changed, deleted

    def folder_badges(changed, deleted):
        badges = []
        if changed:
            changed_text = f"{changed} changed file" + ("s" if changed != 1 else "")
            badges.append(f'<span class="badge folder-changed">{changed_text}</span>')
        if deleted:
            deleted_text = f"{deleted} deleted"
            badges.append(f'<span class="badge deleted">{deleted_text}</span>')
        if not badges:
            badges.append('<span class="badge unchanged">No changes</span>')
        return "".join(badges)

    def render(node):
        rows = []

        for directory_name in sorted(node["directories"], key=str.lower):
            child = node["directories"][directory_name]
            changed, deleted = subtree_counts(child)
            rows.append(
                '<li><details open><summary><span class="tree-row">'
                '<span class="icon">📁</span>'
                f'<span class="tree-name">{html.escape(directory_name)}/</span>'
                f'{folder_badges(changed, deleted)}'
                '</span></summary>'
                f'{render(child)}'
                '</details></li>'
            )

        for filename in sorted(node["files"], key=str.lower):
            record = node["files"][filename]
            safe_name = html.escape(filename)

            if record["deleted"]:
                extension = html.escape(str(record["extension"]))
                size = int(record["size"])
                rows.append(
                    '<li class="deleted-tree-file">'
                    '<span class="tree-row">'
                    '<span class="icon">🗑️</span>'
                    f'<span class="tree-name">{safe_name}</span>'
                    '<span class="badge deleted">Deleted</span>'
                    f'<span class="deleted-tree-meta">{extension} · {size:,} bytes</span>'
                    '</span></li>'
                )
                continue

            report = reports.get(record["path"])
            if report and report.get("report"):
                report_url = html.escape(
                    str(report["report"]).replace("\\", "/"),
                    quote=True,
                )
                status = (
                    '<span class="badge changed">Changed</span>'
                    f'<span class="tree-stats">-{report["removed"]} / +{report["added"]}</span>'
                    f'<a class="tree-link" href="{report_url}">View diff</a>'
                )
            elif report and report.get("report_error"):
                status = '<span class="badge changed status-warn">Report failed</span>'
            else:
                status = '<span class="badge unchanged">No changes</span>'

            rows.append(
                '<li><span class="tree-row">'
                '<span class="icon">📄</span>'
                f'<span class="tree-name">{safe_name}</span>'
                f'{status}'
                '</span></li>'
            )

        return '<ul>' + ''.join(rows or ['<li class="muted">Empty directory</li>']) + '</ul>'

    root_changed, root_deleted = subtree_counts(tree)
    root_name = html.escape(os.path.basename(root.rstrip(os.sep)) or root)

    return (
        '<div class="tree"><ul><li><details open><summary><span class="tree-row">'
        '<span class="icon">📁</span>'
        f'<span class="tree-name">{root_name}/</span>'
        f'{folder_badges(root_changed, root_deleted)}'
        '</span></summary>'
        f'{render(tree)}'
        '</details></li></ul></div>'
    )


def deleted_files_html():
    """Render files removed by --delete in the report overview."""
    if not deleted_files:
        return '<div class="deleted-empty">No files were deleted. Use --delete to remove documentation and non-program assets.</div>'

    rows = []
    for item in sorted(deleted_files, key=lambda entry: entry["path"].lower()):
        path = html.escape(item["path"])
        extension = html.escape(item["extension"] or "no extension")
        size = item["size"]
        rows.append(
            '<li class="deleted-item">'
            f'<span class="deleted-path">{path}</span>'
            f'<span class="deleted-meta">{extension} · {size:,} bytes</span>'
            '<span class="deleted-badge">Deleted</span>'
            '</li>'
        )

    return '<ul class="deleted-list">' + ''.join(rows) + '</ul>'


def make_index(output, root):
    reports = sorted(debug_reports, key=lambda item: str(item["source"]).lower())
    rows = []
    for number, report in enumerate(reports, 1):
        source = html.escape(str(report["source"]))
        if report.get("report"):
            url = html.escape(str(report["report"]).replace("\\", "/"), quote=True)
            source_view = f'<a href="{url}">{source}</a>'
        else:
            source_view = f'{source} <span class="status-warn">Report failed</span>'
        rows.append(f'<li class="report-item"><span class="report-number">#{number}</span>{source_view}<span><span class="status-removed">-{report["removed"]}</span> / <span class="status-added">+{report["added"]}</span></span></li>')

    listing = '<ul class="report-list">' + ''.join(rows) + '</ul>' if rows else '<div class="metadata muted">No modified files.</div>'
    removed = sum(int(item["removed"]) for item in reports)
    added = sum(int(item["added"]) for item in reports)
    failed = sum(bool(item.get("report_error")) for item in reports)
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CommentRemover reports</title><style>{CSS}</style></head><body><main>{html_banner()}<h1>CommentRemover Debug Reports</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Project:</span><span>{html.escape(root)}</span></div><div class="metadata-row"><span class="metadata-label">Generated:</span><span>{datetime.now():%Y-%m-%d %H:%M:%S}</span></div></div><div class="summary"><div class="summary-card">Modified files<span class="summary-value">{len(reports)}</span></div><div class="summary-card">Removed lines<span class="summary-value status-removed">{removed}</span></div><div class="summary-card">Added lines<span class="summary-value status-added">{added}</span></div><div class="summary-card">Failed reports<span class="summary-value status-warn">{failed}</span></div><div class="summary-card">Deleted files<span class="summary-value status-removed">{len(deleted_files)}</span></div></div><section class="section"><h2 class="section-title">Directory structure and change status</h2>{FILTERS}{tree_html(root)}</section><section class="section"><h2 class="section-title">Changed files</h2>{listing}</section><section class="section"><h2 class="section-title">Deleted files (--delete)</h2>{deleted_files_html()}</section><section class="section"><h2 class="section-title">Help</h2><ul class="help-list"><li>Changed only is active by default.</li><li>Deleted files are displayed at their original locations in the same project tree and can be shown with Deleted only.</li><li>With --delete, documentation and media assets are removed; JSON manifests/translations, lock files, templates, source code, configuration files, XML, and runtime text data are preserved.</li><li>Reports use a linear positional comparison instead of difflib.</li><li>Hex colors are preserved in INI-like configuration files.</li><li>Line positions remain comparable.</li></ul></section>{SCRIPT}</main></body></html>'''
    with open(os.path.join(output, "index.html"), "w", encoding="utf-8", newline="") as file:
        file.write(document)


# --delete creates a source-focused copy. Documentation, images, media,
# archives, design files, and compiled artifacts are removed. Important
# program files such as JSON manifests/translations, lock files, templates,
# source code, configuration files, XML, and plain-text runtime data remain.
DELETE_FILE_TYPES = {
    # Documentation and prose
    ".md", ".markdown", ".mdown", ".mkd", ".rst", ".adoc", ".asciidoc",

    # Raster and vector images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".avif",
    ".ico", ".tif", ".tiff", ".svg",

    # Audio
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",

    # Video
    ".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".m4v",

    # Office and fixed-layout documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp",

    # Archives and compressed packages
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz",

    # Design, models, and compiled/binary artifacts
    ".psd", ".ai", ".xd", ".sketch", ".stl", ".obj", ".blend",
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".class", ".jar",
}


HANDLERS = {}

HANDLERS = {}
for extension in (".py", ".yml", ".yaml", ".sh", ".toml", ".rb", ".tf"):
    HANDLERS[extension] = remove_hash_comments
for extension in (".ini", ".cfg", ".conf", ".properties"):
    HANDLERS[extension] = remove_config_hash_comments
for extension in (".java", ".cs", ".c", ".cpp", ".cc", ".h", ".hpp", ".js", ".jsx", ".ts", ".tsx", ".go", ".swift", ".kt", ".kts", ".css", ".scss", ".less", ".rs"):
    HANDLERS[extension] = remove_c_comments
HANDLERS.update({".html": remove_xml_comments, ".htm": remove_xml_comments, ".php": remove_php_comments, ".sql": remove_sql_comments, ".xml": remove_xml_comments, ".xaml": remove_xml_comments, ".svg": remove_xml_comments, ".lua": remove_lua_comments})


def process_file(path, debug, diff_dir, root):
    filename = os.path.basename(path).lower()
    handler = remove_hash_comments if filename == "dockerfile" else HANDLERS.get(os.path.splitext(filename)[1].lower())
    if not handler:
        return
    try:
        with open(path, encoding="utf-8") as file:
            original = file.read()
    except (OSError, UnicodeError) as error:
        print(f"WARNING: Could not read: {path}\n         {error}")
        return

    cleaned = restore_eof(original, handler(original))
    if not has_change(original, cleaned):
        return

    compared = compare_lines(original, cleaned)
    added, removed = change_counts(compared)
    if debug:
        relative = os.path.relpath(path, root)
        try:
            report = make_report(path, original, cleaned, diff_dir, root, compared)
            report_error = None
        except (OSError, MemoryError, ValueError) as error:
            report = None
            report_error = str(error)
            print(f"WARNING: HTML report failed: {relative}\n         {error}")
        debug_reports.append({"source": relative, "report": report, "added": added, "removed": removed, "report_error": report_error})

    try:
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(cleaned)
        changes.append(("CLEANED", path))
    except OSError as error:
        print(f"WARNING: Could not write: {path}\n         {error}")


def walk(root, debug, diff_dir):
    for current, directories, files in os.walk(root):
        for name in files:
            process_file(os.path.join(current, name), debug, diff_dir, root)


def should_delete_file(path):
    """Return True only for explicitly allowlisted disposable asset types."""
    return os.path.splitext(path)[1].lower() in DELETE_FILE_TYPES


def delete_selected_assets(root):
    """Delete allowlisted assets while preserving project/runtime files."""
    removed = 0
    for current, directories, files in os.walk(root):
        directories[:] = [directory for directory in directories if directory != ".git"]
        for name in files:
            path = os.path.join(current, name)
            if not should_delete_file(path):
                continue
            try:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                deleted_files.append({
                    "path": os.path.relpath(path, root),
                    "extension": os.path.splitext(name)[1].lower(),
                    "size": size,
                })
                os.remove(path)
                changes.append(("REMOVED", path))
                removed += 1
            except OSError as error:
                print(f"WARNING: Could not remove non-code file: {path}\n         {error}")
    for current, directories, files in os.walk(root, topdown=False):
        if current != root:
            try:
                if not os.listdir(current):
                    os.rmdir(current)
            except OSError:
                pass
    return removed


def main():
    print(console_banner())
    print()
    parser = argparse.ArgumentParser(
        prog="CommentRemover.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Create a project copy, remove comments and optionally create a source-focused copy.",
        epilog="""Examples:
  Remove comments only:
    python3 CommentRemover.py --path /path/to/project

  Remove comments and create HTML reports:
    python3 CommentRemover.py --path /path/to/project --debug-diff

  Create a source-focused copy without documentation or media assets:
    python3 CommentRemover.py --path /path/to/project --debug-diff --delete
""",
    )
    parser.add_argument("-path", "--path", "-p", "--p", required=True, dest="path", metavar="DIRECTORY", help="project directory")
    parser.add_argument("--debug-diff", action="store_true", dest="debug_diff", help="create filterable HTML reports in a separate folder")
    parser.add_argument(
        "-delete", "--delete", "-d", "--d",
        action="store_true",
        dest="delete",
        help="delete documentation, images, media, archives, and compiled assets from the copy",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")
    args = parser.parse_args()

    changes.clear()
    debug_reports.clear()
    deleted_files.clear()
    source = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(source):
        print("ERROR: Invalid project directory:", source)
        return 1

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = source.rstrip("\\/") + f"_Clean_{timestamp}"
    diff_dir = destination + "_DEBUG-FILE" if args.debug_diff else None

    print("Copying project...")
    try:
        shutil.copytree(source, destination, symlinks=True)
        if diff_dir:
            os.makedirs(diff_dir, exist_ok=False)
    except OSError as error:
        print("ERROR:", error)
        return 1

    print("Removing comments...")
    walk(destination, args.debug_diff, diff_dir)

    if args.delete:
        print("Deleting documentation and non-program assets from copy...")
        removed_assets = delete_selected_assets(destination)
        print(f"Removed non-program files: {removed_assets}")
    else:
        print("All files preserved. Use --delete for a source-focused copy.")

    index_path = None
    if diff_dir:
        index_path = os.path.join(diff_dir, "index.html")
        try:
            make_index(diff_dir, destination)
        except (OSError, MemoryError) as error:
            print("ERROR: Could not create report index:", error)

    print()
    print("Copy-Project:")
    print(destination)
    print()
    if index_path:
        print("Separate DEBUG-FILE report:")
        print(index_path)
        print()

    for action, path in changes:
        print(f"{action:8} : {os.path.relpath(path, destination)}")
    print(f"Changes       : {len(changes)}")
    print(f"Debug reports : {len(debug_reports)}")
    print(f"Report failures: {sum(bool(item.get('report_error')) for item in debug_reports)}")
    print(f"Deleted files  : {len(deleted_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

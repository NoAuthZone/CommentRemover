#!/usr/bin/env python3
"""CommentRemover 1.2 - copy projects, remove comments and create HTML diffs."""

import argparse
import difflib
import html
import os
import re
import shutil
from datetime import datetime

PROGRAM_NAME = "CommentRemover"
PROGRAM_VERSION = "1.2"
PROGRAM_AUTHOR = "NoAuthZone"
PROGRAM_GITHUB = "https://github.com/NoAuthZone/CommentRemover"

changes = []
debug_reports = []


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
    return "".join(c for c in match.group(0) if c in "\r\n")


def remove_hash_comments(text):
    result = []
    for number, line in enumerate(text.splitlines()):
        if number == 0 and line.startswith("#!"):
            result.append(line)
            continue
        out, quote, escaped = [], None, False
        for char in line:
            if escaped:
                out.append(char); escaped = False; continue
            if char == "\\" and quote:
                out.append(char); escaped = True; continue
            if char in ('"', "'"):
                quote = char if quote is None else (None if quote == char else quote)
            if char == "#" and quote is None:
                break
            out.append(char)
        result.append("".join(out).rstrip())
    return restore_eof(text, "\n".join(result))


def remove_c_comments(text):
    out, i, quote, escaped = [], 0, None, False
    while i < len(text):
        char, pair = text[i], text[i:i + 2]
        if escaped:
            out.append(char); escaped = False; i += 1; continue
        if quote:
            out.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            i += 1; continue
        if char in ('"', "'", "`"):
            quote = char; out.append(char); i += 1; continue
        if pair == "//":
            while i < len(text) and text[i] != "\n": i += 1
            continue
        if pair == "/*":
            i += 2
            while i < len(text) - 1 and text[i:i + 2] != "*/":
                if text[i] in "\r\n": out.append(text[i])
                i += 1
            if i < len(text) - 1: i += 2
            continue
        out.append(char); i += 1
    return restore_eof(text, "".join(out))


def remove_sql_comments(text):
    out, i, quote = [], 0, None
    while i < len(text):
        char, pair = text[i], text[i:i + 2]
        if quote:
            out.append(char)
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    out.append(quote); i += 2; continue
                quote = None
            i += 1; continue
        if char in ('"', "'"):
            quote = char; out.append(char); i += 1; continue
        if pair == "--" or char == "#":
            while i < len(text) and text[i] != "\n": i += 1
            continue
        if pair == "/*":
            i += 2
            while i < len(text) - 1 and text[i:i + 2] != "*/":
                if text[i] in "\r\n": out.append(text[i])
                i += 1
            if i < len(text) - 1: i += 2
            continue
        out.append(char); i += 1
    return restore_eof(text, "".join(out))


def remove_xml_comments(text):
    return restore_eof(text, re.sub(r"<!--.*?-->", preserve_newlines, text, flags=re.DOTALL))


def remove_lua_comments(text):
    cleaned = re.sub(r"--\[\[.*?\]\]", preserve_newlines, text, flags=re.DOTALL)
    cleaned = re.sub(r"--.*?$", "", cleaned, flags=re.MULTILINE)
    return restore_eof(text, cleaned)


def remove_php_comments(text):
    out, i, quote, escaped = [], 0, None, False
    while i < len(text):
        char, pair = text[i], text[i:i + 2]
        if escaped:
            out.append(char); escaped = False; i += 1; continue
        if quote:
            out.append(char)
            if char == "\\": escaped = True
            elif char == quote: quote = None
            i += 1; continue
        if char in ('"', "'"):
            quote = char; out.append(char); i += 1; continue
        if pair == "//" or char == "#":
            while i < len(text) and text[i] != "\n": i += 1
            continue
        if pair == "/*":
            i += 2
            while i < len(text) - 1 and text[i:i + 2] != "*/":
                if text[i] in "\r\n": out.append(text[i])
                i += 1
            if i < len(text) - 1: i += 2
            continue
        out.append(char); i += 1
    return restore_eof(text, remove_xml_comments("".join(out)))


CSS = '''
:root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--head:#21262d;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--blue:#58a6ff}*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1800px;margin:auto}h1{color:var(--blue)}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.metadata,.navigation,.section,.summary-card,.program-banner{background:var(--panel);border:1px solid var(--border);border-radius:8px}.metadata,.navigation{padding:16px;margin-bottom:24px}.metadata-row{display:flex;gap:12px;margin:5px 0}.metadata-label{min-width:130px;color:var(--muted)}.program-banner{margin-bottom:24px;overflow:hidden}.program-title{padding:16px;text-align:center;font-size:24px;font-weight:700;background:var(--head);border-bottom:1px solid var(--border)}.program-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--border)}.program-meta>div{display:flex;flex-direction:column;gap:5px;padding:13px 16px;background:var(--panel)}.program-meta span{color:var(--muted);font-size:12px}.section{margin-bottom:28px;overflow:hidden}.section-title{padding:12px 16px;margin:0;background:var(--head);border-bottom:1px solid var(--border)}.code{padding:16px;margin:0;overflow:auto;font:13px/1.5 Consolas,"Cascadia Code",monospace;white-space:pre}.diff-wrapper{overflow:auto}table.diff{width:100%;min-width:900px;border-collapse:collapse;font:12px Consolas,monospace}table.diff td,table.diff th{padding:3px 7px;border:1px solid var(--border);vertical-align:top;white-space:pre-wrap}.diff_header{background:var(--head)}.diff_add{background:#2ea04355}.diff_chg{background:#d2992255}.diff_sub{background:#f8514955}.summary{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}.summary-card{min-width:180px;padding:16px}.summary-value{display:block;margin-top:6px;font-size:28px;font-weight:bold}.status-added{color:#3fb950}.status-removed{color:#f85149}.report-list,.tree ul{list-style:none;margin:0;padding:0}.report-item{display:grid;grid-template-columns:60px 1fr auto;gap:16px;padding:12px 16px;border-bottom:1px solid var(--border)}.report-number,.muted{color:var(--muted)}.tree{padding:16px 20px;overflow:auto}.tree ul ul{padding-left:24px}.tree li{padding:4px 0}.tree details>summary{cursor:pointer}.tree-row{display:inline-flex;align-items:center;gap:10px;min-width:420px}.tree-name{white-space:normal;overflow-wrap:anywhere}.icon{width:20px}.badge{padding:3px 9px;border:1px solid var(--border);border-radius:999px;font-size:11px;font-weight:600}.changed{color:#3fb950;background:#23863633;border-color:#238636}.folder-changed{color:#d2a8ff;background:#8957e533;border-color:#8957e5}.unchanged{color:var(--muted);background:#30363d55}.tree-stats{color:var(--muted);font-size:11px}.tree-link{font-size:12px}.filter-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border)}.filter-button,.filter-search{padding:8px 12px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:7px;font:inherit}.filter-button{cursor:pointer}.filter-button.active{color:white;background:#1f6feb;border-color:#388bfd}.filter-search{min-width:240px;flex:1}.filter-result{color:var(--muted);font-size:12px}.tree li.filter-hidden{display:none!important}.help-list{padding:16px 34px}.help-code{display:block;margin-top:8px;padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);font-family:Consolas,monospace}@media(max-width:700px){body{padding:12px}.program-meta{grid-template-columns:1fr}.report-item{grid-template-columns:1fr}.metadata-row{flex-direction:column}}
'''

FILTERS = '''<div class="filter-bar"><button class="filter-button" data-filter="all">All files</button><button class="filter-button active" data-filter="changed">Changed only</button><button class="filter-button" data-filter="unchanged">Unchanged only</button><input id="tree-search" class="filter-search" type="search" placeholder="Search files and folders..."><span id="filter-result" class="filter-result"></span></div>'''

SCRIPT = r'''<script>
(()=>{const tree=document.querySelector('.tree'),buttons=[...document.querySelectorAll('.filter-button')],search=document.querySelector('#tree-search'),result=document.querySelector('#filter-result');if(!tree)return;let filter='changed';
function row(li){const d=[...li.children].find(x=>x.tagName==='DETAILS');return d?d.querySelector(':scope>summary .tree-row'):[...li.children].find(x=>x.classList&&x.classList.contains('tree-row'));}
function file(li){const r=row(li),i=r&&r.querySelector('.icon');return !!(i&&i.textContent.includes('📄'));}
function status(li){const r=row(li);return r&&r.querySelector('.badge.changed')?'changed':'unchanged';}
function match(li,q){const r=row(li),n=r&&r.querySelector('.tree-name');return !q||!!(n&&n.textContent.toLowerCase().includes(q));}
function visit(li,q){if(file(li)){const visible=(filter==='all'||status(li)===filter)&&match(li,q);li.classList.toggle('filter-hidden',!visible);return visible?1:0;}let hits=0;const ul=li.querySelector(':scope>details>ul');if(ul)[...ul.children].forEach(c=>{if(c.tagName==='LI')hits+=visit(c,q)});li.classList.toggle('filter-hidden',hits===0);const d=li.querySelector(':scope>details');if(d&&hits&&(filter!=='all'||q))d.open=true;return hits;}
function apply(){let hits=0,q=search.value.trim().toLowerCase(),ul=tree.querySelector(':scope>ul');if(ul)[...ul.children].forEach(c=>hits+=visit(c,q));result.textContent=hits+(hits===1?' matching file':' matching files');}
buttons.forEach(b=>b.onclick=()=>{filter=b.dataset.filter;buttons.forEach(x=>x.classList.toggle('active',x===b));apply()});search.oninput=apply;apply();})();
</script>'''


def diff_counts(original, cleaned):
    added = removed = 0
    for line in difflib.ndiff(original.splitlines(), cleaned.splitlines()):
        added += line.startswith("+ ")
        removed += line.startswith("- ")
    return added, removed


def has_change(original, cleaned):
    return original.rstrip("\r\n") != cleaned.rstrip("\r\n")


def back_link(relative):
    parent = os.path.dirname(relative.replace("\\", "/"))
    return "../" * len([p for p in parent.split("/") if p]) + "index.html"


def make_report(path, original, cleaned, output, root):
    relative = os.path.relpath(path, root)
    report_relative = relative + ".html"
    report_path = os.path.join(output, report_relative)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    added, removed = diff_counts(original, cleaned)
    table = difflib.HtmlDiff(tabsize=4, wrapcolumn=120).make_table(original.splitlines(), cleaned.splitlines(), "Original", "Cleaned", context=False, numlines=5)
    doc = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Diff - {html.escape(relative)}</title><style>{CSS}</style></head><body><main>{html_banner()}<div class="navigation"><a href="{html.escape(back_link(report_relative),quote=True)}">&larr; Back to overview</a></div><h1>{html.escape(relative)}</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Removed lines:</span><span class="status-removed">{removed}</span></div><div class="metadata-row"><span class="metadata-label">Added lines:</span><span class="status-added">{added}</span></div></div><section class="section"><h2 class="section-title">Git-style diff</h2><div class="diff-wrapper">{table}</div></section><section class="section"><h2 class="section-title">Original file</h2><pre class="code">{html.escape(original)}</pre></section><section class="section"><h2 class="section-title">Cleaned file</h2><pre class="code">{html.escape(cleaned)}</pre></section></main></body></html>'''
    with open(report_path, "w", encoding="utf-8") as f: f.write(doc)
    return report_relative


def tree_html(root):
    reports = {os.path.normpath(str(x["source"])): x for x in debug_reports}
    def count(path):
        rel = os.path.relpath(path, root)
        if rel == ".": return len(reports)
        prefix = os.path.normpath(rel) + os.sep
        return sum(p.startswith(prefix) for p in reports)
    def render(path):
        try: entries = sorted(os.scandir(path), key=lambda e:(not e.is_dir(follow_symlinks=False),e.name.lower()))
        except OSError as e: return f'<ul><li class="muted">{html.escape(str(e))}</li></ul>'
        rows=[]
        for e in entries:
            if e.name == "_DEBUG_DIFF": continue
            name, rel = html.escape(e.name), os.path.relpath(e.path, root)
            if e.is_dir(follow_symlinks=False):
                n=count(e.path); text="No changes" if not n else f"{n} changed file"+("s" if n!=1 else ""); kind="folder-changed" if n else "unchanged"
                rows.append(f'<li><details open><summary><span class="tree-row"><span class="icon">📁</span><span class="tree-name">{name}/</span><span class="badge {kind}">{text}</span></span></summary>{render(e.path)}</details></li>')
            else:
                report=reports.get(os.path.normpath(rel))
                if report:
                    url=html.escape(str(report["report"]).replace("\\","/"),quote=True); status=f'<span class="badge changed">Changed</span><span class="tree-stats">-{report["removed"]} / +{report["added"]}</span><a class="tree-link" href="{url}">View diff</a>'
                else: status='<span class="badge unchanged">No changes</span>'
                rows.append(f'<li><span class="tree-row"><span class="icon">📄</span><span class="tree-name">{name}</span>{status}</span></li>')
        return '<ul>'+''.join(rows or ['<li class="muted">Empty directory</li>'])+'</ul>'
    n=len(reports); text="No changes" if not n else f"{n} changed file"+("s" if n!=1 else ""); kind="folder-changed" if n else "unchanged"; name=html.escape(os.path.basename(root.rstrip(os.sep)) or root)
    return f'<div class="tree"><ul><li><details open><summary><span class="tree-row"><span class="icon">📁</span><span class="tree-name">{name}/</span><span class="badge {kind}">{text}</span></span></summary>{render(root)}</details></li></ul></div>'


def make_index(output, root):
    reports=sorted(debug_reports,key=lambda x:str(x["source"]).lower()); rows=[]
    for i,r in enumerate(reports,1):
        url=html.escape(str(r["report"]).replace("\\","/"),quote=True); rows.append(f'<li class="report-item"><span class="report-number">#{i}</span><a href="{url}">{html.escape(str(r["source"]))}</a><span><span class="status-removed">-{r["removed"]}</span> / <span class="status-added">+{r["added"]}</span></span></li>')
    listing='<ul class="report-list">'+''.join(rows)+'</ul>' if rows else '<div class="metadata muted">No modified files.</div>'
    removed=sum(int(x["removed"]) for x in reports); added=sum(int(x["added"]) for x in reports)
    doc=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CommentRemover reports</title><style>{CSS}</style></head><body><main>{html_banner()}<h1>CommentRemover Debug Reports</h1><div class="metadata"><div class="metadata-row"><span class="metadata-label">Project:</span><span>{html.escape(root)}</span></div><div class="metadata-row"><span class="metadata-label">Generated:</span><span>{datetime.now():%Y-%m-%d %H:%M:%S}</span></div></div><div class="summary"><div class="summary-card">Modified files<span class="summary-value">{len(reports)}</span></div><div class="summary-card">Removed lines<span class="summary-value status-removed">{removed}</span></div><div class="summary-card">Added lines<span class="summary-value status-added">{added}</span></div></div><section class="section"><h2 class="section-title">Directory structure and change status</h2>{FILTERS}{tree_html(root)}</section><section class="section"><h2 class="section-title">Changed files</h2>{listing}</section><section class="section"><h2 class="section-title">Help</h2><ul class="help-list"><li>Changed only is active by default.</li><li>All files shows the complete tree.</li><li>Unchanged only shows untouched files.</li><li>Search can be combined with every filter.</li><li>Line numbers remain stable because comment line breaks are preserved.</li></ul></section>{SCRIPT}</main></body></html>'''
    with open(os.path.join(output,"index.html"),"w",encoding="utf-8") as f:f.write(doc)


REMOVE={".png",".jpg",".jpeg",".gif",".bmp",".webp",".svg",".ico",".tif",".tiff",".md",".markdown",".pdf",".txt",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".odt",".ods",".mp3",".wav",".ogg",".flac",".mp4",".avi",".mov",".mkv",".webm",".zip",".rar",".7z",".tar",".gz",".psd",".ai",".xd",".dist"}
HANDLERS={}
for ext in (".py",".yml",".yaml",".sh",".ini",".cfg",".conf",".properties",".toml",".rb",".tf"): HANDLERS[ext]=remove_hash_comments
for ext in (".java",".cs",".c",".cpp",".cc",".h",".hpp",".js",".jsx",".ts",".tsx",".go",".swift",".kt",".kts",".css",".scss",".less",".rs"): HANDLERS[ext]=remove_c_comments
HANDLERS.update({".html":remove_xml_comments,".htm":remove_xml_comments,".php":remove_php_comments,".sql":remove_sql_comments,".xml":remove_xml_comments,".xaml":remove_xml_comments,".svg":remove_xml_comments,".lua":remove_lua_comments})


def process_file(path, debug, diff_dir, root):
    handler=remove_hash_comments if os.path.basename(path).lower()=="dockerfile" else HANDLERS.get(os.path.splitext(path)[1].lower())
    if not handler:return
    try:
        with open(path,encoding="utf-8") as f:original=f.read()
    except (OSError,UnicodeError):return
    cleaned=restore_eof(original,handler(original))
    if not has_change(original,cleaned):return
    if debug:
        report=make_report(path,original,cleaned,diff_dir,root);added,removed=diff_counts(original,cleaned);debug_reports.append({"source":os.path.relpath(path,root),"report":report,"added":added,"removed":removed})
    with open(path,"w",encoding="utf-8",newline="") as f:f.write(cleaned)
    changes.append(("CLEANED",path))


def walk(root,debug,diff_dir):
    for current,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if d!="_DEBUG_DIFF"]
        for name in files:process_file(os.path.join(current,name),debug,diff_dir,root)


def is_source_code_file(path):
    """Return True when a file is supported source code/configuration."""
    filename = os.path.basename(path).lower()
    if filename == "dockerfile":
        return True
    return os.path.splitext(filename)[1].lower() in HANDLERS


def keep_code_only(root):
    """Remove every non-code file and subsequently remove empty folders."""
    removed_files = 0

    for current, directories, files in os.walk(root):
        for name in files:
            path = os.path.join(current, name)
            if is_source_code_file(path):
                continue
            try:
                os.remove(path)
                changes.append(("REMOVED", path))
                removed_files += 1
            except OSError as error:
                print(f"WARNING: Could not remove non-code file: {path}")
                print(f"         {error}")

    for current, directories, files in os.walk(root, topdown=False):
        if current == root:
            continue
        try:
            if not os.listdir(current):
                os.rmdir(current)
        except OSError:
            pass

    return removed_files


def main():
    print(console_banner());print()
    parser=argparse.ArgumentParser(prog="CommentRemoverV20.py",formatter_class=argparse.RawDescriptionHelpFormatter,description="Create a code-only project copy, remove comments, preserve line numbers and generate reports in a separate debug folder.",epilog='''Examples:
  python3 CommentRemoverV20.py --path /path/to/project
  python3 CommentRemoverV20.py --path /path/to/project --debug-diff
''')
    parser.add_argument("-path","--path","-p","--p",required=True,dest="path",metavar="DIRECTORY",help="project directory")
    parser.add_argument("--debug-diff",action="store_true",dest="debug_diff",help="create filterable HTML reports")
    parser.add_argument("--version",action="version",version=f"%(prog)s {PROGRAM_VERSION}")
    args=parser.parse_args();changes.clear();debug_reports.clear()
    source=os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(source):print("ERROR: Invalid project directory:",source);return 1
    timestamp=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination=source.rstrip("\\/")+f"_Clean_{timestamp}"
    diff_dir=destination+"_DEBUG-FILE" if args.debug_diff else None

    print("Copying project...")
    try:
        shutil.copytree(source,destination)
        if diff_dir:
            os.makedirs(diff_dir,exist_ok=False)
    except OSError as e:
        print("ERROR:",e)
        return 1

    print("Removing comments...")
    walk(destination,args.debug_diff,diff_dir)

    print("Removing non-code files from copy...")
    removed_non_code=keep_code_only(destination)
    print(f"Removed non-code files: {removed_non_code}")

    index_path=None
    if diff_dir:
        index_path=os.path.join(diff_dir,"index.html")
        make_index(diff_dir,destination)
    print()
    print("Copy-Project:")
    print(destination)
    print()

    if index_path:
        print("Separate DEBUG-FILE report:")
        print(index_path)
        print()
    for action,path in changes:print(f"{action:8} : {os.path.relpath(path,destination)}")
    print(f"Changes      : {len(changes)}");print(f"Debug reports: {len(debug_reports)}")
    return 0


if __name__=="__main__":raise SystemExit(main())

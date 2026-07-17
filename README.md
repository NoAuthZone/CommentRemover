# CommentRemover

## Description

**CommentRemover** is a command-line tool that creates a clean copy of a software project by removing comments from supported source files.

All modifications are performed exclusively on the copied project, ensuring that the original files remain untouched.

Optionally, the tool can also remove non-source assets such as images, documents, archives, media files, and other unnecessary resources to create a lightweight, source-code-only project suitable for distribution, backups, code reviews, or static analysis.

---

## Features

- Creates a timestamped copy of the original project.    
- Removes comments from multiple programming languages.    
- Preserves the original project.    
- Optionally removes unnecessary non-source files.    
- Recursively processes entire project directories.
    

---

## Project Copy

```text
Original:  my-project
Created:   my-project_Clean_2026-07-17_20-30-15
```

---

# Usage

## Remove Comments

```bash
python3 CommentRemover.py -path /path/to/project
```

**Actions performed**

- Create a copy of the project.    
- Remove comments from supported source files.
    

## Remove Comments and Unwanted Files

```bash
python3 CommentRemover.py -path /path/to/project -delete
```

**Actions performed**

- Create a timestamped copy of the project.
- Remove comments from supported source files.
- Delete unnecessary non-source files (optional with `-delete`).

> **Note:** All operations are performed on the copied project. The original project is never modified.

|Category| Removed File Types|
|---|---|
|Images|`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, `.svg`, `.ico`, `.tif`, `.tiff`|
|Documents|`.pdf`, `.txt`, `.md`, `.markdown`|
|Office|`.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`|
|Media|`.mp3`, `.wav`, `.ogg`, `.flac`, `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`|
|Archives|`.zip`, `.rar`, `.7z`, `.tar`, `.gz`|
|Design|`.psd`, `.ai`, `.xd`|

---

## Supported Comment Formats

| Style      | Languages                                                                   | Syntax                                       |
| ---------- | --------------------------------------------------------------------------- | -------------------------------------------- |
| Hash       | Python, Shell, YAML, TOML, INI, Configuration                               | `# Comment`                                  |
| C-Style    | C, C++, Java, C#, JavaScript, TypeScript, PHP, CSS, Rust, Go, Swift, Kotlin | `// Comment``/* Block Comment */`            |
| SQL        | SQL                                                                         | `-- Comment``# Comment``/* Block Comment */` |
| HTML / XML | HTML, XML, SVG, XAML                                                        | `<!-- Comment -->`                           |
| Lua        | Lua                                                                         | `-- Comment``--[[ Block Comment ]]`          |

### Notes

- Supports both single-line and multi-line comments.    
- Preserves string literals whenever supported.    
- All modifications are applied only to the copied project.    

---

## Supported Source Files

|Category|Extensions|
|---|---|
|Python|`.py`|
|Java|`.java`|
|C / C++|`.c`, `.cpp`, `.h`, `.hpp`|
|C#|`.cs`|
|JavaScript|`.js`, `.jsx`|
|TypeScript|`.ts`, `.tsx`|
|PHP|`.php`|
|Web|`.html`, `.css`, `.scss`, `.xml`|
|SQL|`.sql`|
|Lua|`.lua`|
|Configuration|`.yml`, `.yaml`, `.ini`, `.cfg`, `.toml`|

---


---

## Example Output

```text
$ python CommentRemoverV2.py  -path /home/kali/test/test-files --delete

-------------------------------------------------------------

                     CommentRemover

-------------------------------------------------------------

 Version   : 1.0
 Author    : NoAuthZone
 GitHub    : https://github.com/NoAuthZone/CommentRemover

-------------------------------------------------------------

Copying project...
   DONE.

Removing comments...
   DONE.

Deleting files...
   DONE.


-------------------------------------------------------------
Copy-Project: 
/home/kali/test/test-files_Clean_2026-07-17_20-37-17
-------------------------------------------------------------
                                                             
CLEANED  : /home/kali/test-files_Clean_2026-07-17_20-37-17/test.html
CLEANED  : /home/kali/test-files_Clean_2026-07-17_20-37-17/test.php
REMOVED  : /home/kali/test-files_Clean_2026-07-17_20-37-17/to-del-files/music.flac
REMOVED  : /home/kali/test-files_Clean_2026-07-17_20-37-17/to-del-files/document.txt
                                                             
  Changes: 4

-------------------------------------------------------------

                       ALL DONE

-------------------------------------------------------------
```

#!/usr/bin/env python3

import argparse
import os
import re
import shutil
from datetime import datetime

changes = []

# ==========================================================
# Comment Remover
# ==========================================================

def remove_hash_comments(text: str) -> str:
    """
    Remove comments with #
    Suitable for: Python, YAML, TOML, CFG
    """
    result = []

    for line in text.splitlines():
        in_quotes = False
        quote_char = None
        cleaned = ""

        for char in line:
            if char in ('"', "'"):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif quote_char == char:
                    in_quotes = False

            if char == "#" and not in_quotes:
                break

            cleaned += char

        result.append(cleaned.rstrip())

    return "\n".join(result)


def remove_slash_comments(text: str) -> str:
    """
    Remove:
        // ...
        /* ... */
    """

    # Block Comments
    text = re.sub(
        r"/\*.*?\*/",
        "",
        text,
        flags=re.DOTALL,
    )

    # Line Comments
    text = re.sub(
        r"(?<!:)//.*?$",
        "",
        text,
        flags=re.MULTILINE,
    )

    return text

def remove_sql_comments(text: str) -> str:
    """
    Removes SQL comments:

        -- Comment
        # Comment
        /* Block Comment */

    Ignore comments within:
        'String'
        "String"
    """


    result = []
    i = 0
    length = len(text)

    in_single_quote = False
    in_double_quote = False

    while i < length:

        char = text[i]

        # SQL String mit '
        if char == "'" and not in_double_quote:
            result.append(char)

            # Escape ''
            if in_single_quote and i + 1 < length and text[i + 1] == "'":
                result.append("'")
                i += 2
                continue
              
            in_single_quote = not in_single_quote
            i += 1
            continue

        # SQL String with "
        if char == '"' and not in_single_quote:
            result.append(char)
            in_double_quote = not in_double_quote
            i += 1
            continue

        # Remove comments only outside of strings
        if not in_single_quote and not in_double_quote:

            # -- Comment
            if text[i:i+2] == "--":

                while i < length and text[i] != "\n":
                    i += 1
                continue

            # # Comment
            if char == "#":

                while i < length and text[i] != "\n":
                    i += 1

                continue

            # /* Block Comment */
            if text[i:i+2] == "/*":

                i += 2

                while i < length - 1:

                    if text[i:i+2] == "*/":
                        i += 2
                        break

                    i += 1

                continue

        result.append(char)
        i += 1


    return "".join(result)
    
def remove_yaml_comments(text: str) -> str:
    """
    Remove comments with #
    Suitable for: Python, YAML, TOML, CFG
    """
    result = []

    for line in text.splitlines():
        in_quotes = False
        quote_char = None
        cleaned = ""

        for char in line:
            if char in ('"', "'"):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif quote_char == char:
                    in_quotes = False

            if char == "#" and not in_quotes:
                break

            cleaned += char

        result.append(cleaned.rstrip())

    return "\n".join(result)
    

def remove_xml_comments(text: str) -> str:
    """
    Remove:
        <!-- -->
    """

    return re.sub(
        r"<!--.*?-->",
        "",
        text,
        flags=re.DOTALL,
    )

def remove_lua_comments(text: str) -> str:
    """
    Remove:
        -- ...
        --[[ ... ]]
    """

    text = re.sub(
        r"--\[\[.*?\]\]",
        "",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"--.*?$",
        "",
        text,
        flags=re.MULTILINE,
    )

    return text
    
def remove_html_comments(text: str) -> str:
    result = []
    in_comment = False

    for line in text.splitlines():
        cleaned = ""
        i = 0

        while i < len(line):
            if not in_comment:
                start = line.find("<!--", i)

                if start == -1:
                    cleaned += line[i:]
                    break

                cleaned += line[i:start]
                i = start + 4
                in_comment = True

            else:
                end = line.find("-->", i)

                if end == -1:
                    i = len(line)
                else:
                    i = end + 3
                    in_comment = False

        result.append(cleaned.rstrip())

    return "\n".join(result)
    
def remove_php_comments(text: str) -> str:
    """
    Remove PHP comments.
    Supports:
      // ...
      # ...
      /* ... */
    """
    result = []
    in_block_comment = False

    for line in text.splitlines():
        in_quotes = False
        quote_char = None
        cleaned = ""

        i = 0
        while i < len(line):

            if in_block_comment:
                end = line.find("*/", i)
                if end == -1:
                    i = len(line)
                    continue
                else:
                    i = end + 2
                    in_block_comment = False
                    continue

            char = line[i]

            # Recognizing Strings
            if char in ('"', "'"):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif quote_char == char:
                    in_quotes = False

            if not in_quotes:

                # Block comment
                if line.startswith("/*", i):
                    in_block_comment = True
                    i += 2
                    continue
                # //
                if line.startswith("//", i):
                    break

                # #
                if char == "#":
                    break

            cleaned += char
            i += 1

        result.append(cleaned.rstrip())

    return "\n".join(result)




# ==========================================================
# Delete Files
# ==========================================================

def delete_file(file_path: str) -> bool:

    extension = os.path.splitext(file_path)[1].lower()

    if extension in REMOVE_FILE_TYPES:
        try:
            os.remove(file_path)
            changes.append(("REMOVED", file_path))
            return True
        except Exception:
            pass

    return False

def delete_files(directory: str):

    for root, _, files in os.walk(directory):
        for filename in files:
            delete_file(os.path.join(root, filename))


# ==========================================================
# Edit File (Comments only)
# ==========================================================

def process_file(file_path: str):

    extension = os.path.splitext(file_path)[1].lower()

    handler = COMMENT_HANDLERS.get(extension)

    if handler is None:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception:
        return

    cleaned = handler(original)

    if cleaned != original:
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.write(cleaned)
	
    changes.append(("CLEANED", file_path))




def show_banner():

    print("						                                              		")
    print("-------------------------------------------------------------")
    print("							                                               	")
    print("                     CommentRemover		                  		")
    print("							                                               	")
    print("-------------------------------------------------------------")
    print("						                                              		")
    print(f" Version   : 1.0					                                	")
    print(f" Author    : NoAuthZone					                            ")
    print(f" GitHub    : https://github.com/NoAuthZone/CommentRemover 	")
    print("							                                              	")
    print("-------------------------------------------------------------")
    print("								                                              ")
    
    
def remove_php_file_comments(text: str) -> str:
    """
    Remove comments from PHP files.
    Supports:
      PHP: //, #, /* */
      HTML: <!-- -->
    """

    text = remove_php_comments(text)
    text = remove_html_comments(text)

    return text

# ==========================================================
# File Types -> Comment Feature
# ==========================================================

REMOVE_FILE_TYPES = {
    # Pictures
	".png",".jpg",".jpeg",".gif",".bmp",".webp",".svg",".ico",".tif",".tiff",
    # Documentation
	".md",".markdown",".pdf",".txt",
    # Office
	".doc",".docx",".xls",".xlsx",".ppt",".pptx",".odt",".ods",
    # Audio
	".mp3",".wav",".ogg",".flac",
    # Video
	".mp4",".avi",".mov",".mkv",".webm",
    # Archive
	".zip",".rar",".7z",".tar",".gz",
    # Other Assets
	".psd",".ai",".xd",".dist"
}

COMMENT_HANDLERS = {
    # Python / YAML / Shell
	".py"        	: remove_hash_comments,
	".yml"       	: remove_yaml_comments,
	".sh"        	: remove_hash_comments,
	".ini"       	: remove_hash_comments,
	".cfg"       	: remove_hash_comments,
	".conf"      	: remove_hash_comments,
	".properties"	: remove_hash_comments,
	".toml"      	: remove_hash_comments,
	".rb"        	: remove_hash_comments,
	".dockerfile"	: remove_hash_comments,
	".tf"        	: remove_hash_comments,
	    
    # XML Files
        ".yaml"      	: remove_hash_comments,

    # C-like languages
	".java"   	: remove_slash_comments,
	".cs"     	: remove_slash_comments,
	".c"      	: remove_slash_comments,
	".cpp"    	: remove_slash_comments,
	".cc"    	: remove_slash_comments,
	".h"     	: remove_slash_comments,
	".hpp"     	: remove_slash_comments,
	".js"        	: remove_slash_comments,
	".jsx"       	: remove_slash_comments,
	".ts"        	: remove_slash_comments,
	".tsx"       	: remove_slash_comments,
	".go"        	: remove_slash_comments,
	".swift"     	: remove_slash_comments,
	".kt"        	: remove_slash_comments,
	".kts"  	: remove_slash_comments,
	".css"       	: remove_slash_comments,
	".scss"      	: remove_slash_comments,
	".less"	 	: remove_slash_comments,
	".rs"        	: remove_slash_comments,
  
   # html 
	".html"		: remove_php_comments,
	".php"       	: remove_php_file_comments,

    # SQL
	".sql"		: remove_sql_comments,

    # XML / HTML
	".xml"		: remove_xml_comments,
	".htm"		: remove_xml_comments,
	".xaml"		: remove_xml_comments,
	".svg"		: remove_xml_comments,
    
    # Lua
	".lua"		: remove_lua_comments,
}



def process_project(directory: str):

    for root, _, files in os.walk(directory):

        for filename in files:
            process_file(os.path.join(root, filename))


def main():


    show_banner()

    parser = argparse.ArgumentParser(
        description="Copy project and optionally delete unwanted files."
    )

    parser.add_argument(
        "-path",
        "--path",
        "--p",
        "-p",
        required=True,
        dest="path",
        help="Project directory"
    )

    parser.add_argument(
        "-delete",
        "--delete",
        "-d",
        "--d",
        dest="delete",
        action="store_true",
        help="Delete unwanted files (.png, .jpg, .pdf, ...)"
    )

    args = parser.parse_args()

    # Reset Changes Per Run
    changes.clear()

    source = os.path.abspath(args.path)

    if not os.path.exists(source):
        print("Project directory does not exist:")
        print(source)
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = source.rstrip("\\/") + f"_Clean_{timestamp}"

    print("Copying project...			")
    shutil.copytree(source, destination)
    print("   DONE.				")
    print("                                              								")

     # Always remove comments
    print("Removing comments...")
    process_project(destination)
    print("   DONE.")

    # Delete files only with -delete
    if args.delete:
        print("                                              								")
        print("Deleting files...		                                        ")
        delete_files(destination)
        print("   DONE.				                                              ")
        print("                                              								")

    
    print("                                              								")
    print("-------------------------------------------------------------")
    print("Copy-Project: ")
    print(destination)
    print("-------------------------------------------------------------")
    print("                                                             ")

    if changes:
        for action, file_path in changes:
            print(f"{action:8} : {file_path}")

        print("                                                             ")
        print("  Changes:", len(changes))
    else:
        print("  No changes.")

    print("								                                              ")
    print("-------------------------------------------------------------")
    print("								                                              ")
    print("                       ALL DONE				                      ")
    print("								                                              ")
    print("-------------------------------------------------------------")
    print("								                                              ")


if __name__ == "__main__":
    main()

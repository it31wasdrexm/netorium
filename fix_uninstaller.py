from pathlib import Path

content = Path("netorium/services/uninstaller.py").read_text()

content = content.replace(
    'return ("cmd.exe", "/d", "/c", " & ".join(cleanup_lines))',
    'return ("windows-batch-cleanup", *cleanup_lines)'
)

old_detached = """    if len(args) >= 4 and args[0] == "cmd.exe" and args[1] == "/d" and args[2] == "/c":
        cleanup_body = args[3]"""

new_detached = """    if len(args) >= 1 and args[0] == "windows-batch-cleanup":
        cleanup_lines = args[1:]
        cleanup_body = "\\n".join(cleanup_lines)"""
content = content.replace(old_detached, new_detached)

old_check = """        if args[3].find('netorium.exe') != -1:"""
new_check = """        if '\\n'.join(cleanup_lines).find('netorium.exe') != -1:"""
content = content.replace(old_check, new_check)

Path("netorium/services/uninstaller.py").write_text(content)
print("Updated uninstaller.py")

Option Explicit
Dim shell, fs, base, result
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
base = fs.GetParentFolderName(WScript.ScriptFullName)
result = shell.Run("powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & fs.BuildPath(base, "launch.ps1") & """", 0, True)
WScript.Quit result

Option Explicit

Dim shell, fso, installRoot, toolsDir, powershellExe, guardianScript, commandLine

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)
installRoot = fso.GetParentFolderName(toolsDir)
If WScript.Arguments.Count >= 1 Then
    installRoot = WScript.Arguments.Item(0)
End If

powershellExe = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
guardianScript = fso.BuildPath(installRoot, "tools\windows_guardian.ps1")
commandLine = """" & powershellExe & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & guardianScript & """ -InstallRoot """ & installRoot & """ -StartWatcher -Quiet"

shell.Run commandLine, 0, True

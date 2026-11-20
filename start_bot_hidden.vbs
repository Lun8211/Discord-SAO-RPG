Option Explicit
Dim fso, sh, baseDir, batPath, envPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = baseDir & "\start_bot.bat"
envPath = baseDir & "\.env"

If Not fso.FileExists(envPath) Then
    sh.Run """" & batPath & """", 1, False
Else
    sh.Run """" & batPath & """ --hidden", 0, False
End If

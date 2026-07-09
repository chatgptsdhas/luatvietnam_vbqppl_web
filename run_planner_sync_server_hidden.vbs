' ============================================================
' Chay run_planner_sync_server_hidden.bat HOAN TOAN AN (khong hien
' bat ky cua so console/PowerShell nao tren desktop).
'
' Duoc goi boi Scheduled Task "HAS_Planner_Sync_Server" (xem
' install_planner_sync_task.ps1). windowStyle = 0 (an) va
' waitOnReturn = True de WScript tien trinh nay song suot vong doi
' cua server ben trong — nho vay Task Scheduler theo doi dung trang
' thai "dang chay" va ap dung ExecutionTimeLimit / RestartOnFailure
' chinh xac (neu server crash, wscript.exe cung thoat theo va Task
' Scheduler se tu restart theo cau hinh RestartCount/RestartInterval).
' ============================================================

Option Explicit

Dim fso, shell, scriptDir, batPath

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_planner_sync_server_hidden.bat"

shell.CurrentDirectory = scriptDir

' windowStyle 0 = an hoan toan (khong minimized, khong flash), True = doi tien trinh con ket thuc
shell.Run """" & batPath & """", 0, True

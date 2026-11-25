Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = oWS.SpecialFolders("Desktop") & "\Advanced AI Studio.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = oWS.CurrentDirectory & "\run_web.bat"
oLink.WorkingDirectory = oWS.CurrentDirectory
oLink.Description = "Advanced Enterprise AI Research & Intelligence Studio"
oLink.WindowStyle = 1
oLink.Save
WScript.Echo "Success! Desktop Shortcut 'Advanced AI Studio' created on your Desktop."

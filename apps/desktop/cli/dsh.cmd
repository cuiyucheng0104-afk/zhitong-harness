@echo off
setlocal DisableDelayedExpansion
set "ELECTRON_RUN_AS_NODE=1"
rem zhitong increment: win.executableName is ztsgai (ASCII, independent of the console code page).
"%~dp0..\..\..\..\ztsgai.exe" --expose-internals "%~dp0..\..\..\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js" %*
exit /b %errorlevel%

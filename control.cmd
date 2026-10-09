@echo off
chcp 65001 >nul
cd /d "%~dp0"
wscript.exe "%~dp0sys\launch.vbs"
if errorlevel 1 (
  echo Controller failed. See the error above.
  pause
)

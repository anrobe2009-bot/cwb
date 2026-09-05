@echo off
rem CWB neu starten: laufendes CWB beenden, dann ohne Konsolenfenster neu starten.
cd /d "%~dp0"

rem Nur die pythonw-Prozesse beenden, die fenster.py ausfuehren.
for /f "usebackq tokens=1 delims=" %%P in (`wmic process where "name='pythonw.exe' and CommandLine like '%%fenster.py%%'" get ProcessId /value 2^>nul ^| find "="`) do (
    for /f "tokens=2 delims==" %%I in ("%%P") do taskkill /f /pid %%I >nul 2>&1
)

rem Neu starten ohne stehenbleibendes Konsolenfenster.
start "" pythonw "%~dp0core\fenster.py"
exit

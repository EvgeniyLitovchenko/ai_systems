@echo off
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
 "..\.venv\Scripts\python.exe" app.py
) else if exist ".venv\Scripts\python.exe" (
 ".venv\Scripts\python.exe" app.py
) else (
 echo Please follow README.md to install Python 3.11+, Ollama and requirements.
)
pause

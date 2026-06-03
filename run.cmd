@echo off
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Environnement manquant. Executez :
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
"%PY%" "%~dp0src\main.py" %*

@echo off
REM Double-click or run from cmd — starts the web dashboard (dashboard.py)
REM Optional env: PHARMFLOW_HOST, PHARMFLOW_PORT, PHARMFLOW_WS_PORT (see dashboard.py docstring)
if not defined PHARMFLOW_HOST  set "PHARMFLOW_HOST=127.0.0.1"
if not defined PHARMFLOW_PORT  set "PHARMFLOW_PORT=8080"

cd /d "%~dp0"
where py >nul 2>&1 && (
  py -3 dashboard.py
  exit /b %ERRORLEVEL%
)
python dashboard.py
exit /b %ERRORLEVEL%

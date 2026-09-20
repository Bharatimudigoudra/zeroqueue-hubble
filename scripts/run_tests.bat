@echo off
REM Runs the automated test suite.
cd /d "%~dp0.."
call conda activate GenAI
pytest test -q
pause

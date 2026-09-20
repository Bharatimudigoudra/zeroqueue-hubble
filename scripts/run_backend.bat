@echo off
REM Starts the complete app on http://localhost:8000.
cd /d "%~dp0.."
call conda activate GenAI
uvicorn app.main:app --reload --reload-dir app --port 8000

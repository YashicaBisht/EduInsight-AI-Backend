@echo off
echo Starting EduInsight AI Backend on 0.0.0.0:8000...
echo Ready for Android Physical Phone and Cloud Access
cd /d "%~dp0"
call .\venv\Scripts\activate.bat
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause

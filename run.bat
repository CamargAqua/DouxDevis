@echo off
REM Lance l'appli avec le Python du venv du projet (pas le Python global Windows,
REM qui n'a pas les dépendances comme extract-msg installées).
"%~dp0venv\Scripts\python.exe" "%~dp0app.py"
pause

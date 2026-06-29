@echo off
REM Double-cliquez sur ce fichier pour démarrer NotebookLM Azure.
REM Voir GUIDE-UTILISATEUR.md pour le mode d'emploi complet.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
pause

@echo off
rem Inicia o ecossistema Vagamundo completo (Backend Python + Frontend Angular).
rem Duplo clique neste arquivo; feche a janela ou pressione Ctrl+C para encerrar.
cd /d "%~dp0"
npm run dev
if %errorlevel% neq 0 (
  node dev.js
)
pause

@echo off
setlocal
set "ROOT_DIR=%~dp0.."
set "TIKTOKEN_CACHE_DIR=%ROOT_DIR%\resources\tiktoken"
echo [dev.bat] TIKTOKEN_CACHE_DIR=%TIKTOKEN_CACHE_DIR%
cd /d "%ROOT_DIR%"
npm run dev

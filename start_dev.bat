@echo off
echo ========================================
echo Enterprise AI Chatbot — Dev Environment
echo ========================================
echo.
echo NOTE: Requires .env to be configured first.
echo See docs\setup\RUN_LOCAL.md for setup steps.
echo.

echo [1/2] Starting Backend on port 8000...
start "ChatbotEnterprise-Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo Waiting 5 seconds for backend to initialize...
timeout /t 5 /nobreak >nul

echo [2/2] Starting Frontend on port 3000...
start "ChatbotEnterprise-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 3000 --strictPort"

echo.
echo ========================================
echo Services Started
echo ========================================
echo Backend API:  http://localhost:8000/docs
echo Frontend UI:  http://localhost:3000
echo.
echo After seed: use the credentials printed by scripts.seed_demo
echo ========================================
echo.
echo Press any key to STOP all services...
pause >nul

echo.
echo Stopping services...
taskkill /FI "WINDOWTITLE eq ChatbotEnterprise-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChatbotEnterprise-Frontend*" /F >nul 2>&1
echo Services stopped.

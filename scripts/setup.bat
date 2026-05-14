@echo off
:: setup.bat — One-shot dev environment bootstrap for Chatbot_Enterprise-AI (Windows)
:: Usage: scripts\setup.bat
setlocal EnableDelayedExpansion

echo.
echo  =====================================================
echo   Chatbot Enterprise-AI -- Dev Setup (Windows)
echo  =====================================================
echo.

:: ── 1. Check prerequisites ─────────────────────────────────────────────────────
echo [setup] Checking prerequisites...

where docker >nul 2>&1 || (
    echo [X] Docker not found. Install Docker Desktop: https://docs.docker.com/get-docker/
    exit /b 1
)
echo [OK] docker found

docker compose version >nul 2>&1
if %errorlevel% equ 0 (
    set DC=docker compose
) else (
    where docker-compose >nul 2>&1 || (
        echo [X] Docker Compose not found. Install Docker Desktop.
        exit /b 1
    )
    set DC=docker-compose
)
echo [OK] docker compose found

where python >nul 2>&1 || where python3 >nul 2>&1 || (
    echo [X] Python not found. Install Python 3.12+: https://www.python.org/downloads/
    exit /b 1
)
echo [OK] python found

:: ── 2. Create backend\.env from template ───────────────────────────────────────
set ENV_FILE=backend\.env
set ENV_EXAMPLE=backend\.env.example

if not exist "%ENV_EXAMPLE%" (
    echo [X] backend\.env.example not found. Run from the project root directory.
    exit /b 1
)

if exist "%ENV_FILE%" (
    echo [!] %ENV_FILE% already exists -- skipping generation.
    echo     Delete it and re-run to regenerate secrets.
) else (
    echo [setup] Generating %ENV_FILE% with secure random secrets...
    copy "%ENV_EXAMPLE%" "%ENV_FILE%" >nul

    :: Generate secrets using Python (available on all Windows Python installs)
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set JWT_SECRET=%%i
    for /f %%i in ('python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"') do set ENC_KEY=%%i
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(16))"') do set REDIS_PASS=%%i

    :: Replace placeholders using PowerShell (more reliable than findstr/sed on Windows)
    powershell -Command "(Get-Content '%ENV_FILE%') -replace 'JWT_SECRET_KEY=.*', 'JWT_SECRET_KEY=!JWT_SECRET!' | Set-Content '%ENV_FILE%'"
    powershell -Command "(Get-Content '%ENV_FILE%') -replace 'ENCRYPTION_KEY=.*', 'ENCRYPTION_KEY=!ENC_KEY!' | Set-Content '%ENV_FILE%'"
    powershell -Command "(Get-Content '%ENV_FILE%') -replace 'REDIS_PASSWORD=.*', 'REDIS_PASSWORD=!REDIS_PASS!' | Set-Content '%ENV_FILE%'"

    echo [OK] Secrets generated and written to %ENV_FILE%
)

:: ── 3. Database setup choice ───────────────────────────────────────────────────
echo.
echo Database configuration:
echo   1) Use Docker Compose (local PostgreSQL -- easiest for dev)
echo   2) Use an existing PostgreSQL URL (Neon, Supabase, RDS, etc.)
echo.
set /p DB_CHOICE="Choose [1/2] (default: 1): "
if "%DB_CHOICE%"=="" set DB_CHOICE=1

set SKIP_PG=false
if "%DB_CHOICE%"=="2" (
    set /p CUSTOM_DB_URL="Paste your DATABASE_URL (postgresql://...): "
    if not "!CUSTOM_DB_URL!"=="" (
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^DATABASE_URL=.*', 'DATABASE_URL=!CUSTOM_DB_URL!' | Set-Content '%ENV_FILE%'"
        echo [OK] DATABASE_URL updated in %ENV_FILE%
        set SKIP_PG=true
    ) else (
        echo [!] No URL entered -- keeping default (local Docker)
    )
)

:: ── 4. API keys (optional) ─────────────────────────────────────────────────────
echo.
echo [!] Optional: add your LLM API keys to %ENV_FILE%
echo     - ANTHROPIC_API_KEY  (Claude models)
echo     - OPENAI_API_KEY     (GPT models)
echo     - GEMINI_API_KEY     (Google Gemini)
echo.
set /p ADD_KEYS="Add API keys now? [y/N]: "
if /i "%ADD_KEYS%"=="y" (
    set /p ANT_KEY="  ANTHROPIC_API_KEY (Enter to skip): "
    if not "!ANT_KEY!"=="" (
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^ANTHROPIC_API_KEY=.*', 'ANTHROPIC_API_KEY=!ANT_KEY!' | Set-Content '%ENV_FILE%'"
    )
    set /p OAI_KEY="  OPENAI_API_KEY (Enter to skip): "
    if not "!OAI_KEY!"=="" (
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^OPENAI_API_KEY=.*', 'OPENAI_API_KEY=!OAI_KEY!' | Set-Content '%ENV_FILE%'"
    )
    set /p GEM_KEY="  GEMINI_API_KEY (Enter to skip): "
    if not "!GEM_KEY!"=="" (
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^GEMINI_API_KEY=.*', 'GEMINI_API_KEY=!GEM_KEY!' | Set-Content '%ENV_FILE%'"
    )
    echo [OK] API keys saved.
)

:: ── 5. Build and start Docker Compose ─────────────────────────────────────────
echo.
set /p START_NOW="Build and start all services now? [Y/n]: "
if "%START_NOW%"=="" set START_NOW=Y

if /i "%START_NOW%"=="y" (
    echo [setup] Building Docker images (this may take a few minutes on first run)...

    if "%SKIP_PG%"=="true" (
        %DC% up -d --build redis backend frontend
    ) else (
        %DC% up -d --build
    )

    echo [OK] Services started.

    :: ── 6. Wait for backend ───────────────────────────────────────────────────
    echo [setup] Waiting for backend to be ready...
    set WAITED=0
    :WAIT_LOOP
    curl -sf http://localhost:8000/health >nul 2>&1
    if %errorlevel% equ 0 goto BACKEND_READY
    timeout /t 2 /nobreak >nul
    set /a WAITED+=2
    if !WAITED! geq 60 (
        echo [!] Backend not responding after 60s. Check: %DC% logs backend
        goto SKIP_MIGRATION
    )
    goto WAIT_LOOP
    :BACKEND_READY
    echo [OK] Backend is healthy.

    :: ── 7. Run migrations ─────────────────────────────────────────────────────
    echo [setup] Running Alembic migrations...
    %DC% exec backend alembic upgrade head
    if %errorlevel% equ 0 (
        echo [OK] Migrations applied.
    ) else (
        echo [!] Migration failed -- check logs.
    )

    :: ── 8. Seed demo users ────────────────────────────────────────────────────
    echo.
    set /p SEED_NOW="Seed demo users (admin + alice)? [Y/n]: "
    if "%SEED_NOW%"=="" set SEED_NOW=Y
    if /i "%SEED_NOW%"=="y" (
        echo [setup] Seeding demo users...
        %DC% exec backend python -m scripts.seed_demo
        if %errorlevel% equ 0 (
            echo [OK] Demo users created.
        ) else (
            echo [!] Seed failed -- may already exist.
        )
    )
    :SKIP_MIGRATION
) else (
    echo.
    echo [setup] Skipped. When ready, run:
    echo   %DC% up -d --build
    echo   %DC% exec backend alembic upgrade head
)

:: ── Done ───────────────────────────────────────────────────────────────────────
echo.
echo  =====================================================
echo   Setup complete!
echo  =====================================================
echo.
echo   Frontend  -^>  http://localhost:3000
echo   Backend   -^>  http://localhost:8000
echo   API Docs  -^>  http://localhost:8000/docs
echo.
echo   Useful commands:
echo     make dev        -- start all services
echo     make logs       -- tail all logs
echo     make migrate    -- run pending migrations
echo     make test       -- run backend tests
echo     make down       -- stop all services
echo.
endlocal

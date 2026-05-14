#!/usr/bin/env bash
# setup.sh — One-shot dev environment bootstrap for Chatbot_Enterprise-AI
# Usage: bash scripts/setup.sh
set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[setup]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${CYAN}║   Chatbot Enterprise-AI — Dev Setup              ║${RESET}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${RESET}"
echo ""

# ── 1. Check prerequisites ─────────────────────────────────────────────────────
info "Checking prerequisites..."

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        error "$1 is required but not installed. $2"
    fi
    success "$1 found"
}

check_cmd docker   "Install Docker Desktop: https://docs.docker.com/get-docker/"
check_cmd openssl  "Install OpenSSL (usually pre-installed on Linux/Mac)"
check_cmd python3  "Install Python 3.12+: https://www.python.org/downloads/"

DOCKER_COMPOSE_CMD=""
if docker compose version &>/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    error "Docker Compose not found. Install Docker Desktop (includes Compose v2)."
fi
success "docker compose found ($DOCKER_COMPOSE_CMD)"

# ── 2. Create backend/.env from template ───────────────────────────────────────
ENV_FILE="backend/.env"
ENV_EXAMPLE="backend/.env.example"

if [[ ! -f "$ENV_EXAMPLE" ]]; then
    error "backend/.env.example not found. Are you running from the project root?"
fi

if [[ -f "$ENV_FILE" ]]; then
    warn "$ENV_FILE already exists — skipping generation (delete it to regenerate)"
else
    info "Generating $ENV_FILE with secure random secrets..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"

    # Generate JWT_SECRET_KEY (64 hex chars = 256-bit)
    JWT_SECRET=$(openssl rand -hex 32)
    sed -i.bak "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT_SECRET}|" "$ENV_FILE"

    # Generate ENCRYPTION_KEY (32 bytes → base64, exactly 44 chars)
    ENCRYPTION_KEY=$(openssl rand -base64 32)
    sed -i.bak "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENCRYPTION_KEY}|" "$ENV_FILE"

    # Generate REDIS_PASSWORD (32 hex chars)
    REDIS_PASS=$(openssl rand -hex 16)
    sed -i.bak "s|REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASS}|" "$ENV_FILE"

    # Clean up sed backup files (macOS creates .bak)
    rm -f "${ENV_FILE}.bak"

    success "Secrets generated and written to $ENV_FILE"
fi

# ── 3. Database setup choice ───────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Database configuration:${RESET}"
echo "  1) Use Docker Compose (local PostgreSQL — easiest for dev)"
echo "  2) Use an existing PostgreSQL URL (Neon, Supabase, RDS, etc.)"
echo ""
read -rp "Choose [1/2] (default: 1): " DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

if [[ "$DB_CHOICE" == "2" ]]; then
    echo ""
    read -rp "Paste your DATABASE_URL (postgresql://...): " CUSTOM_DB_URL
    if [[ -n "$CUSTOM_DB_URL" ]]; then
        if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
            sed -i.bak "s|^DATABASE_URL=.*|DATABASE_URL=${CUSTOM_DB_URL}|" "$ENV_FILE"
        else
            echo "DATABASE_URL=${CUSTOM_DB_URL}" >> "$ENV_FILE"
        fi
        rm -f "${ENV_FILE}.bak"
        success "DATABASE_URL updated in $ENV_FILE"
        SKIP_PG_SERVICE=true
    else
        warn "No URL entered — keeping default (local Docker)"
        SKIP_PG_SERVICE=false
    fi
else
    SKIP_PG_SERVICE=false
fi

# ── 4. API keys (optional but recommended) ─────────────────────────────────────
echo ""
warn "Optional: add your LLM API keys to $ENV_FILE"
echo "  - ANTHROPIC_API_KEY  (Claude models)"
echo "  - OPENAI_API_KEY     (GPT models)"
echo "  - GEMINI_API_KEY     (Google Gemini)"
echo ""
read -rp "Add API keys now? [y/N]: " ADD_KEYS
if [[ "${ADD_KEYS,,}" == "y" ]]; then
    read -rp "  ANTHROPIC_API_KEY (Enter to skip): " ANT_KEY
    [[ -n "$ANT_KEY" ]] && sed -i.bak "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANT_KEY}|" "$ENV_FILE"

    read -rp "  OPENAI_API_KEY (Enter to skip): " OAI_KEY
    [[ -n "$OAI_KEY" ]] && sed -i.bak "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${OAI_KEY}|" "$ENV_FILE"

    read -rp "  GEMINI_API_KEY (Enter to skip): " GEM_KEY
    [[ -n "$GEM_KEY" ]] && sed -i.bak "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${GEM_KEY}|" "$ENV_FILE"

    rm -f "${ENV_FILE}.bak"
    success "API keys saved."
fi

# ── 5. Build and start Docker Compose ─────────────────────────────────────────
echo ""
read -rp "Build and start all services now? [Y/n]: " START_NOW
START_NOW="${START_NOW:-Y}"

if [[ "${START_NOW,,}" == "y" ]]; then
    info "Building Docker images (this may take a few minutes on first run)..."

    if [[ "$SKIP_PG_SERVICE" == true ]]; then
        # Start everything except postgres if using external DB
        $DOCKER_COMPOSE_CMD up -d --build redis backend frontend
    else
        $DOCKER_COMPOSE_CMD up -d --build
    fi

    success "Services started."

    # ── 6. Wait for backend health ─────────────────────────────────────────────
    info "Waiting for backend to be ready..."
    MAX_WAIT=60
    WAITED=0
    until curl -sf http://localhost:8000/health &>/dev/null; do
        sleep 2
        WAITED=$((WAITED + 2))
        if [[ $WAITED -ge $MAX_WAIT ]]; then
            warn "Backend not responding after ${MAX_WAIT}s. Check logs: $DOCKER_COMPOSE_CMD logs backend"
            break
        fi
        echo -n "."
    done
    echo ""
    success "Backend is healthy."

    # ── 7. Run database migrations ─────────────────────────────────────────────
    info "Running Alembic migrations..."
    $DOCKER_COMPOSE_CMD exec backend alembic upgrade head && success "Migrations applied." || warn "Migration failed — check logs."

    # ── 8. Seed demo users ─────────────────────────────────────────────────────
    echo ""
    read -rp "Seed demo users (admin + alice)? [Y/n]: " SEED_NOW
    SEED_NOW="${SEED_NOW:-Y}"
    if [[ "${SEED_NOW,,}" == "y" ]]; then
        info "Seeding demo users..."
        $DOCKER_COMPOSE_CMD exec backend python -m scripts.seed_demo && success "Demo users created." || warn "Seed failed — may already exist."
    fi
else
    echo ""
    info "Skipped. When ready, run:"
    echo "  $DOCKER_COMPOSE_CMD up -d --build"
    echo "  $DOCKER_COMPOSE_CMD exec backend alembic upgrade head"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}║   Setup complete!                                ║${RESET}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${RESET}"
echo ""
echo "  Frontend  → http://localhost:3000"
echo "  Backend   → http://localhost:8000"
echo "  API Docs  → http://localhost:8000/docs"
echo ""
echo "  Useful commands:"
echo "    make dev        — start all services"
echo "    make logs       — tail all logs"
echo "    make migrate    — run pending migrations"
echo "    make test       — run backend tests"
echo "    make down       — stop all services"
echo ""

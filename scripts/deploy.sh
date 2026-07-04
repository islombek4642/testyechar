#!/usr/bin/env bash
# Testyechar bot — Ubuntu serverda bitta buyruq bilan joylashtirish.
#
#   bash scripts/deploy.sh
#
# Qayta ishga tushirish/yangilash uchun ham xuddi shu buyruq ishlatiladi:
# skript kodni git orqali yangilaydi va konteynerni qayta quradi.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Testyechar bot: joylashtirish boshlandi ($REPO_ROOT)"

# 1. Kodni yangilash (agar git repo bo'lsa)
if [ -d .git ]; then
  echo "==> git pull ..."
  git pull --ff-only || echo "OGOHLANTIRISH: git pull muvaffaqiyatsiz — joriy kod bilan davom etiladi."
fi

# 2. .env tayyorligini tekshirish
if [ ! -f .env ]; then
  cp .env.example .env
  echo "XATO: .env yaratildi, lekin bo'sh. BOT_TOKEN, BOT_ADMIN_ID, ANTHROPIC_API_KEY qiymatlarini to'ldiring:"
  echo "  nano \"$REPO_ROOT/.env\""
  echo "so'ng qayta ishga tushiring: bash scripts/deploy.sh"
  exit 1
fi
if grep -q "REPLACE" .env; then
  echo "XATO: .env faylida hali to'ldirilmagan REPLACE qiymatlar bor. Avval uni tahrirlang:"
  echo "  nano \"$REPO_ROOT/.env\""
  exit 1
fi

# 3. Docker mavjudligini tekshirish, kerak bo'lsa o'rnatish (Ubuntu)
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Docker topilmadi, o'rnatilmoqda (Ubuntu uchun)..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
  echo "OGOHLANTIRISH: Docker guruhiga qo'shildingiz. Agar 'permission denied' xatosi chiqsa,"
  echo "tizimga qayta kiring (logout/login yoki 'newgrp docker') va skriptni qayta ishga tushiring."
fi

DOCKER_COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker-compose"
fi

# 4. Bind-mount qilinadigan papkalarni oldindan yaratish
mkdir -p data logs output

# 5. Qurish va ishga tushirish
echo "==> Docker image qurilmoqda..."
$DOCKER_COMPOSE build

echo "==> Bot konteyneri ishga tushirilmoqda..."
$DOCKER_COMPOSE up -d

echo "==> Tayyor! Holatni tekshirish: $DOCKER_COMPOSE ps"
echo "==> Loglarni ko'rish uchun:      $DOCKER_COMPOSE logs -f"

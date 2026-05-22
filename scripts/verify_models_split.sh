#!/usr/bin/env bash
# verify_models_split.sh
# Запускати з кореня проекту (де manage.py)
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        fail "Не знайдено python3 або python"
    fi
fi

echo "=== Перевірка розбиття core/models ==="
echo ""

# 1. models.py не повинен існувати
if [ -f "core/models.py" ]; then
    echo "     Виконайте: mv core/models.py core/models.py.bak"
    fail "core/models.py ще існує! Видаліть або перейменуйте його перед застосуванням."
fi
ok "core/models.py відсутній"

# 2. Всі файли пакету на місці
EXPECTED_FILES=(
    "core/models/__init__.py"
    "core/models/base.py"
    "core/models/barcodes.py"
    "core/models/directories.py"
    "core/models/inventory.py"
    "core/models/labels.py"
    "core/models/stock.py"
    "core/models/warehouse.py"
)
for f in "${EXPECTED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        fail "Відсутній файл: $f"
    fi
    ok "Існує: $f"
done

# 3. Синтаксична перевірка
echo ""
echo "--- py_compile ---"
for f in "${EXPECTED_FILES[@]}"; do
    "$PYTHON_BIN" -m py_compile "$f" && ok "$f" || fail "Синтаксична помилка в $f"
done

# 4. Django check
echo ""
echo "--- django check ---"
"$PYTHON_BIN" manage.py check && ok "django check пройшов" || fail "django check виявив помилки"

# 5. Головна перевірка: чи не з'явились нові міграції
echo ""
echo "--- makemigrations --check ---"
# makemigrations --check повертає 0, якщо нових міграцій немає.
# Не прив’язуємося до тексту "No changes detected", бо він може відрізнятися залежно від версії/локалі Django.
"$PYTHON_BIN" manage.py makemigrations --check --dry-run && \
    ok "Нових міграцій немає — розбиття чисте" || {
    warn "Django хоче створити нові міграції. Перевірте вручну:"
    "$PYTHON_BIN" manage.py makemigrations --dry-run || true
    fail "Розбиття змінило структуру моделей для Django"
}

echo ""
echo -e "${GREEN}=== Всі перевірки пройдено ===${NC}"

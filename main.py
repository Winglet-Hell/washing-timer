#!/usr/bin/env python3
"""
Washing Timer Bot - Главный файл запуска

Telegram бот для установки таймеров стирки
"""

import sys
from pathlib import Path

# Добавляем путь к папке src в Python path
project_root = Path(__file__).parent
src_path = project_root / "src"
config_path = project_root / "config"

sys.path.insert(0, str(src_path))

# Импортируем и запускаем основной модуль
if __name__ == "__main__":
    from washing_timer import main
    main() 
"""Зафиксировать в onec/ext/ExtVersion.txt хеш последнего коммита, тронувшего onec/ext/.

Запускать после каждого изменения расширения (до коммита):

    cd backend && uv run python scripts/bump_ext_version.py

Скрипт пишет хеш в ExtVersion.txt и подставляет его в ВерсияРасширения()
менеджера a1c_ИнструментДерево (строка `Версия = "<хеш>"`), затем добавляет оба
файла в git-индекс — коммитятся вместе с правкой BSL. Тулза get_extension_version
отдаёт версию модели, check_extension_freshness сравнивает с git.

Если onec/ext/ ещё ни разу не коммитился — пишет хеш HEAD (первый бамп).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = REPO_ROOT / "onec" / "ext"
VERSION_FILE = EXT_DIR / "ExtVersion.txt"
# Версия захардкожена в менеджере обработки (строка `Версия = "<хеш>"`).
MANAGER_MODULE = EXT_DIR / "DataProcessors" / "a1c_ИнструментДерево" / "Ext" / "ManagerModule.bsl"
# Точка с запятой обязательна: при подстановке она сохраняется из захваченной группы.
VERSION_LINE_RE = re.compile(r'^(\tВерсия = ")[0-9a-f]{40}(");', re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    if not (REPO_ROOT / ".git").exists():
        print(f"не git-репозиторий: {REPO_ROOT}")
        return 1
    try:
        commit = _git("log", "-1", "--format=%H", "--", "onec/ext")
    except subprocess.CalledProcessError:
        commit = ""
    if not commit:
        # Папка ещё не в истории — бампим HEAD (первый коммит расширения).
        commit = _git("rev-parse", "HEAD")
    VERSION_FILE.write_text(commit + "\n", encoding="utf-8")
    # Подставляем хеш в BSL — тулза get_extension_version читает его отсюда.
    if MANAGER_MODULE.exists():
        bsl = MANAGER_MODULE.read_text(encoding="utf-8")
        new_bsl, count = VERSION_LINE_RE.subn(rf"\g<1>{commit}\g<2>", bsl)
        if count != 1:
            print(f"ошибка: строка `Версия = \"<хеш>\"` в {MANAGER_MODULE} не найдена (найдено {count})")
            return 1
        MANAGER_MODULE.write_text(new_bsl, encoding="utf-8")
    else:
        print(f"ошибка: нет модуля менеджера {MANAGER_MODULE}")
        return 1
    _git("add", "--", str(VERSION_FILE.relative_to(REPO_ROOT)), str(MANAGER_MODULE.relative_to(REPO_ROOT)))
    print(f"ExtVersion.txt + ManagerModule.bsl: {commit} (добавлено в индекс, коммить вместе с правкой)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

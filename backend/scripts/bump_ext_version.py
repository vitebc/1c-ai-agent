"""Зафиксировать версию расширения 1С после изменения onec/ext/.

Запускать после каждого изменения расширения (до коммита):

    cd backend && uv run python scripts/bump_ext_version.py

Скрипт:
1. Находит хеш последнего коммита, тронувшего onec/ext/ (или HEAD, если папка
   ещё не в истории).
2. Считает количество коммитов, тронувших onec/ext/ за сегодня (для суффикса NN);
   если есть неоткоммиченные изменения — +1.
3. Формирует версию расширения: YY.MMDD.NN (YY — год, MMDD — месяц+день,
   NN — порядковый номер правки расширения за день, 2 цифры).
4. Пишет хеш в onec/ext/ExtVersion.txt.
5. Подставляет хеш в <Comment> и версию в <Version> в onec/ext/Configuration.xml.
6. Подставляет хеш в строку `Версия = "<хеш>";` менеджера a1c_ИнструментДерево.
7. Добавляет все три файла в git-индекс — коммитятся вместе с правкой BSL.

Тулза get_extension_version отдаёт версию модели, check_extension_freshness
сравнивает хеш из ExtVersion.txt (git) с хешем из базы.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = REPO_ROOT / "onec" / "ext"
VERSION_FILE = EXT_DIR / "ExtVersion.txt"
CONFIG_XML = EXT_DIR / "Configuration.xml"
# Версия захардкожена в менеджере обработки (строка `Версия = "<хеш>";`).
MANAGER_MODULE = EXT_DIR / "DataProcessors" / "a1c_ИнструментДерево" / "Ext" / "ManagerModule.bsl"

_COMMENT_RE = re.compile(r"(<Comment>)([^<]*)(</Comment>)")
_VERSION_RE = re.compile(r"(<Version>)([^<]*)(</Version>)")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _count_commits_today() -> int:
    """Количество коммитов, тронувших onec/ext/ за сегодня (включая текущий бамп)."""
    today = date.today().isoformat()
    try:
        out = _git(
            "log", "--format=%H", "--date=short",
            "--since", f"{today} 00:00:00",
            "--", "onec/ext",
        )
    except subprocess.CalledProcessError:
        out = ""
    lines = [line for line in out.splitlines() if line.strip()]
    count = len(lines)
    # Неоткоммиченные изменения в onec/ext/ — текущий бамп станет следующей правкой.
    status = _git("status", "--porcelain", "--", "onec/ext")
    if status.strip():
        count += 1
    return max(count, 1)


def main() -> int:
    if not (REPO_ROOT / ".git").exists():
        print(f"не git-репозиторий: {REPO_ROOT}")
        return 1

    # 1. Хеш последнего коммита, тронувшего onec/ext/.
    try:
        commit = _git("log", "-1", "--format=%H", "--", "onec/ext")
    except subprocess.CalledProcessError:
        commit = ""
    if not commit:
        # Папка ещё не в истории — бампим HEAD (первый коммит расширения).
        commit = _git("rev-parse", "HEAD")

    # 2. Версия расширения: YY.MMDD.NN
    today = date.today()
    nn = _count_commits_today()
    ext_version = f"{today.year % 100:02d}.{today.strftime('%m%d')}.{nn:02d}"

    # 3. ExtVersion.txt — хеш (read_git_ext_version читает первую строку).
    VERSION_FILE.write_text(commit + "\n", encoding="utf-8")

    # 4. Configuration.xml — <Comment> = хеш, <Version> = YY.MMDD.NN
    if not CONFIG_XML.exists():
        print(f"ошибка: нет {CONFIG_XML}")
        return 1
    # Читаем как байты: сохраняем BOM и CRLF без изменений.
    raw = CONFIG_XML.read_bytes()
    xml = raw.decode("utf-8")
    if not _COMMENT_RE.search(xml):
        print(f"ошибка: <Comment> не найден в {CONFIG_XML}")
        return 1
    if not _VERSION_RE.search(xml):
        print(f"ошибка: <Version> не найден в {CONFIG_XML}")
        return 1
    xml = _COMMENT_RE.sub(lambda m: f"{m.group(1)}{commit}{m.group(3)}", xml, count=1)
    xml = _VERSION_RE.sub(lambda m: f"{m.group(1)}{ext_version}{m.group(3)}", xml, count=1)
    CONFIG_XML.write_bytes(xml.encode("utf-8"))

    # 5. BSL — строка `Версия = "<хеш>";` (замена по префиксу, без regex-subn).
    if MANAGER_MODULE.exists():
        # Читаем как байты: сохраняем BOM и CRLF без изменений.
        raw_bsl = MANAGER_MODULE.read_bytes()
        bsl = raw_bsl.decode("utf-8")
        new_line = f'\tВерсия = "{commit}";'
        lines = bsl.split("\n")
        replaced = 0
        for i, line in enumerate(lines):
            if line.startswith('\tВерсия = "'):
                lines[i] = new_line
                replaced += 1
        if replaced != 1:
            print(f"ошибка: строка `Версия = \"<хеш>\"` в {MANAGER_MODULE} не найдена (найдено {replaced})")
            return 1
        MANAGER_MODULE.write_bytes("\n".join(lines).encode("utf-8"))
        # Самопроверка: хеш подставлен и точка с запятой на месте.
        written = MANAGER_MODULE.read_bytes().decode("utf-8")
        if new_line not in written:
            print(f"ошибка: самопроверка не прошла, строка `{new_line}` в {MANAGER_MODULE} отсутствует")
            return 1
    else:
        print(f"ошибка: нет модуля менеджера {MANAGER_MODULE}")
        return 1

    # 6. Добавляем все три файла в индекс.
    _git("add", "--",
         str(VERSION_FILE.relative_to(REPO_ROOT)),
         str(CONFIG_XML.relative_to(REPO_ROOT)),
         str(MANAGER_MODULE.relative_to(REPO_ROOT)))

    print(f"ExtVersion.txt: {commit}")
    print(f"Configuration.xml: Comment={commit}, Version={ext_version}")
    print(f'ManagerModule.bsl: Версия = "{commit}"')
    print("(добавлено в индекс, коммить вместе с правкой)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

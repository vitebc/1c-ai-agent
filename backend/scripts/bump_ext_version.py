"""Зафиксировать в onec/ext/ExtVersion.txt хеш последнего коммита, тронувшего onec/ext/.

Запускать после каждого изменения расширения (до коммита):

    cd backend && uv run python scripts/bump_ext_version.py

Скрипт пишет хеш и сам добавляет ExtVersion.txt в git-индекс — файл коммитится
вместе с правкой BSL. Расширение читает версию через ОбщийРеквизит(Строка),
тулза get_extension_version отдаёт её модели, check_extension_freshness
сравнивает с git.

Если onec/ext/ ещё ни разу не коммитился — пишет хеш HEAD (первый бамп).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = REPO_ROOT / "onec" / "ext"
VERSION_FILE = EXT_DIR / "ExtVersion.txt"


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
    _git("add", "--", str(VERSION_FILE.relative_to(REPO_ROOT)))
    print(f"ExtVersion.txt: {commit} (добавлено в индекс, коммить вместе с правкой)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

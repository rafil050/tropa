"""Запуск тестов в GitHub Actions: обычный вывод плюс аннотации ::error для каждого упавшего теста,
чтобы причина была видна прямо в отчёте сборки (и через API), без чтения полного лога."""

import sys
import unittest
from pathlib import Path


def annotate(test, text: str) -> None:
    tail = "\n".join(text.strip().splitlines()[-12:])
    message = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    title = str(test).replace(":", " ").replace(",", " ")[:200]
    print(f"::error title={title}::{message}", flush=True)


def main() -> int:
    here = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(here), top_level_dir=str(here))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, text in result.failures + result.errors:
        annotate(test, text)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

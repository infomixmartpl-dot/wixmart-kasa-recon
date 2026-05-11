"""Top-level entry point для PyInstaller.

Не міститься всередині пакета `recon_backend` — це навмисно, щоб PyInstaller
правильно завантажив пакет як модуль (а не як top-level script).

Альтернативи (всі мають вади):
- `pyinstaller -m recon_backend.launcher` — не підтримується ONEDIR.
- `pyinstaller recon_backend/launcher.py` — ламає relative imports всередині пакета.
- entry-point у `[project.scripts]` через console_script — гарно для pip, але PyInstaller-у все одно потрібен top-level .py.

Тому маленький проміжний модуль що тільки робить імпорт і виклик `run()`.
"""

from recon_backend.launcher import run

if __name__ == "__main__":
    run()

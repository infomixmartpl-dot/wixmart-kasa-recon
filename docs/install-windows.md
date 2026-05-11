# Встановлення на Windows

Є два режими роботи. Обирай той що зручніше — обидва підтримуються.

| Режим | Коли використовувати | Швидкість оновлень |
|-------|---------------------|---------------------|
| **A. Dev через git pull** | Активна розробка, часті оновлення | ~5 секунд через `git pull` |
| **B. Embedded .exe** | Готовий продакт, оновлення раз на тиждень | ~7-10 хв через GitHub Actions + скачування zip |

---

## Режим A — Dev через git pull (рекомендую зараз)

### Раз поставити
1. **GitHub Desktop** — скачай з https://desktop.github.com/ → залогінься своїм GitHub-акаунтом.
2. У GitHub Desktop → **File → Clone repository** → обери `infomixmartpl-dot/wixmart-kasa-recon` → клонуй у `C:\Programs\KasaRecon\` (або куди зручно).
3. **Python 3.11+** — скачай з https://python.org/downloads/ → постав з галочкою **«Add python.exe to PATH»**.
4. У PowerShell з кореня репо: `.\scripts\setup-windows.ps1` — створить venv і поставить залежності.
5. Скачай останній `kasa_recon-...-windows.zip` з GitHub Actions → розпакуй у будь-яку папку. Це твій frontend (UI).

### Щодня працювати
1. **Підняти бекенд:** подвійний клік на `scripts\start-backend.bat`. Відкриється консольне вікно з логами — не закривай.
2. **Запустити UI:** подвійний клік на `kasa_recon.exe` (з розпакованої папки). Він побачить що бекенд уже слухає на 8765 і не запускатиме власного.
3. **Працюй** — додавай ФОПи, тестуй OData, тощо.

### Підтягнути свіжий код
**Варіант 1 — через GitHub Desktop:**
1. У GitHub Desktop → **Fetch origin** → **Pull origin**.
2. У консолі з бекендом → Ctrl+C → закрити вікно.
3. Подвійний клік на `scripts\start-backend.bat` знову.

**Варіант 2 — одним кліком:**
- Подвійний клік на `scripts\update-and-restart.bat` — зробить git pull, прибере старий процес з 8765, запустить новий.

> UI оновлюється **тільки коли є UI-зміни** — тоді скачаєш новий `kasa_recon-...-windows.zip` (рідко). Більшість моїх правок будуть у бекенді — git pull і все.

### Структура файлів

```
C:\Programs\KasaRecon\
├── .git\                    ← git метадані
├── backend\
│   ├── .venv\               ← Python venv (створено setup-скриптом)
│   ├── recon_backend\
│   └── pyproject.toml
├── frontend\                ← (Flutter dev-source, не потрібен якщо UI з zip)
├── scripts\
│   ├── setup-windows.ps1
│   ├── start-backend.bat
│   └── update-and-restart.bat
└── kasa_recon\              ← розпакований UI з zip
    └── kasa_recon.exe
```

### Дані

- БД: `%LOCALAPPDATA%\KasaRecon\recon.db` (переживає переустановки)
- Логи бекенду: `%LOCALAPPDATA%\KasaRecon\backend.log`

---

## Режим B — Embedded .exe (без Python окремо)

Якщо хочеш максимально просту установку (на машині де нема Python і не буде розробки):

1. Скачай `kasa_recon-...-windows.zip` з GitHub Actions:
   - https://github.com/infomixmartpl-dot/wixmart-kasa-recon/actions
   - Найвищий run «Build Windows .exe» → внизу артефакт → клац.
2. Розпакуй кудись, наприклад `C:\Programs\KasaRecon\`.
3. Подвійний клік на `kasa_recon.exe`.

У цьому варіанті бекенд **запакований всередину**: коли UI стартує — він стартує `recon_backend\recon_backend.exe` як subprocess.

**Оновлення:** скачуєш свіжий zip, замінюєш папку. БД у `%LOCALAPPDATA%` зберігається.

---

## Підключення до 1С OData

Незалежно від режиму, конфігурація OData робиться у формі ФОПа всередині UI:
- **OData base URL** — `http://<host>/<база>/odata/standard.odata`
- **Login** + **Password** — 1С користувач з повними правами

Активація OData у самій 1С (раз):
1. **Конфігуратор → Адміністрування → Налаштування публікації на веб-сервері**
2. Закладка «Загальні» → ☑️ **«Публикация стандартного интерфейса OData»**
3. Перепублікувати

Перевірка: `http://<host>/<база>/odata/standard.odata/$metadata` у браузері — має повернути XML.

---

## Troubleshooting

### Бекенд не стартує — `ImportError` або помилка PyInstaller

Зайди в режим A (через git pull + Python) — він не залежить від PyInstaller і легше дебажити. Лог у `%LOCALAPPDATA%\KasaRecon\backend.log`.

### Порт 8765 зайнятий

Швидше за все у тебе вже працює інший інстанс бекенду. Знайди і прибий:
```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### UI каже «Не вдалось запустити бекенд»

В embedded режимі (B) — перевір лог `%LOCALAPPDATA%\KasaRecon\backend.log`.

В dev-режимі (A) — переконайся що `start-backend.bat` справді запустив бекенд (має бути напис `Application startup complete. Uvicorn running on http://127.0.0.1:8765` у консолі).

### Скинути базу і почати з нуля

```powershell
Remove-Item -Recurse "$env:LOCALAPPDATA\KasaRecon"
```

# Встановлення на Windows

Все в одному `.exe` — додаток сам стартує вбудований Python-бекенд. Нічого окремо ставити не треба.

## Крок 1. Скачати zip з GitHub

Після кожного `git push` у `main` GitHub Actions автоматично збирає Windows-білд.

**Через браузер:**
1. Зайди на: `https://github.com/infomixmartpl-dot/wixmart-kasa-recon/actions`
2. Найвищий run «Build Windows .exe» → внизу артефакт `kasa_recon-YYYYMMDD-XXXXXXX-windows` → клац → скачається zip.

**Або через `gh` з терміналу:**
```bash
cd ~/Downloads
gh run download -R infomixmartpl-dot/wixmart-kasa-recon --name kasa_recon-YYYYMMDD-XXXXXXX-windows
```

> **Для іменних релізів:** `git tag v0.1.0 && git push --tags` — GitHub зробить **Release** у розділі Releases з красивим zip.

## Крок 2. Розпакувати і запустити

1. Розпакувати zip кудись, наприклад у `C:\Programs\KasaRecon\`.
2. Двічі клацнути на **`kasa_recon.exe`**.
3. З'явиться сплеш-екран «Запускаю бекенд...» (1-3 секунди) → відкриється головний UI.

**Усе.** Python окремо ставити не треба, NSSM, служб налаштовувати — теж.

## Що там всередині

У папці:
```
KasaRecon/
├── kasa_recon.exe           ← фронтенд (Flutter), на нього клацаєш
├── *.dll                    ← рантайм Flutter
├── data/                    ← Flutter assets
└── recon_backend/
    ├── recon_backend.exe    ← бекенд (PyInstaller-запакований Python)
    └── *.dll                ← Python runtime + бібліотеки
```

Коли запускаєш `kasa_recon.exe`:
1. Він шукає `recon_backend/recon_backend.exe` поряд і стартує його як subprocess.
2. Бекенд слухає на `127.0.0.1:8765` (тільки локально — недоступний з мережі).
3. Фронтенд чекає поки `/health` відповість.
4. Коли закриваєш вікно — бекенд автоматично вбивається.

## Де лежать дані

| Що | Шлях |
|----|------|
| База звірок (SQLite) | `%LOCALAPPDATA%\KasaRecon\recon.db` |
| Логи бекенду | `%LOCALAPPDATA%\KasaRecon\backend.log` (ротується по 2 МБ × 5 файлів) |

> Це означає що **БД переживає переустановку додатку**. Просто перезаписав папку з .exe — стара база на місці. Бекапити можна: скопіюй `%LOCALAPPDATA%\KasaRecon\` куди завгодно.

## Як оновити версію

1. Скачай новий zip.
2. Стули додаток.
3. Розпакуй поверх старої папки (або видалити стару → розпакувати нову).
4. Запусти `.exe`.

БД нікуди не дінеться — вона в `%LOCALAPPDATA%`, а не в папці додатку.

## Troubleshooting

### «Запускаю бекенд...» зависає або show error

Перевір лог:
```powershell
type "$env:LOCALAPPDATA\KasaRecon\backend.log"
```

Типові причини:
- **Порт 8765 зайнятий** — у тебе паралельно ще щось працює на цьому порту (інший інстанс додатку?). Стули.
- **Антивірус заблокував `recon_backend.exe`** — додай винятки на папку з додатком.
- **Файл бекенду відсутній** — перевір що у zip розпакувалась підпапка `recon_backend\` з `.exe`.

### Як запустити бекенд окремо для debug

```powershell
cd "C:\Programs\KasaRecon\recon_backend"
.\recon_backend.exe
```

Має написати щось як `Application startup complete` і слухати на 8765.
Тоді в браузері: `http://127.0.0.1:8765/docs` — Swagger UI з усіма endpoints.

### Скинути базу і почати з нуля

```powershell
Remove-Item -Recurse "$env:LOCALAPPDATA\KasaRecon"
```
Наступний запуск створить порожню БД.

## Підключення до 1С OData (майбутній крок)

Коли підключимо OData-клієнт у бекенді, у формі ФОПа треба буде ввести:
- **OData base URL** — `http://localhost/<твоя_база>/odata/standard.odata`
- **Login / Password** — від користувача 1С з повними правами.

Налаштування OData в УНФ: Конфігуратор → Адміністрування → Налаштування публікації на веб-сервері → ☑️ «Публикация стандартного интерфейса OData» → Опублікувати.

Перевірка: відкрий `http://localhost/<база>/odata/standard.odata/$metadata` у браузері — має повернути XML.

# WixMart Kasa Recon

Звірка ПриватБанк ↔ Каса 1С (УНФ 1.6 для України). Знаходить непроведені операції,
пересорти між касами, готує проводку через 1С OData.

## Архітектура

```
┌──────────────────────────┐         ┌────────────────────────────┐
│   Flutter Desktop        │  HTTP   │   FastAPI бекенд           │
│   (Windows + macOS)      ├────────►│   (Python, Windows-служба) │
│                          │         │                            │
│   • вибір ФОПа           │         │   • SQLite (стан)          │
│   • дашборд звірок       │         │   • Privat24 Business API  │
│   • перегляд операцій    │         │   • 1С OData               │
│   • прев'ю проводки      │         └──────────┬─────────────────┘
└──────────────────────────┘                    │
                                                ▼
                                       1С УНФ 1.6 OData
```

## Структура репо

| Папка | Що |
|-------|------|
| `backend/` | FastAPI бекенд + SQLAlchemy + OData/Privat клієнти |
| `frontend/` | Flutter Desktop UI (Windows + macOS) |
| `recon/` | Старий Python CLI (legacy, ядро алгоритму перенесене в backend) |
| `data/` | Локальні дані: виписки Privat, вивантаження УНФ. **НЕ в git.** |
| `reports/` | Згенеровані Excel-звіти. **НЕ в git.** |
| `1c-epf/` | Інструкція з .epf обробки 1С (legacy, після OData write не потрібна) |
| `.github/workflows/` | GitHub Actions: build Windows .exe |

## Як запустити локально (для розробки на Mac)

### 1. Backend
```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/uvicorn recon_backend.main:app --port 8000 --reload
```

### 2. Frontend
```bash
cd frontend
flutter pub get
flutter run -d macos      # macOS
# або
flutter run -d windows    # Windows
```

### 3. Перший запуск UI
1. Відкривається стартовий екран → натисни **«Додати ФОПа»**.
2. У sidebar обери **«Рахунки і каси»** → додай касу і банк-рахунок з мапінгом.
3. **«Завантаження»** → залий виписку Privat (CSV) + вивантаження УНФ (XLSX).
4. **«Дашборд» → «Нова звірка»** → обери період → запусти.

## Як зібрати Windows .exe

Просто запостити в `main` — GitHub Actions сам збере і додасть артефакт у release.

Локально на Windows:
```powershell
cd frontend
flutter build windows --release
# Готовий .exe — у frontend/build/windows/x64/runner/Release/
```

## Деплой бекенду на Windows-сервер (де 1С)

1. На сервер по RDP → встановити Python 3.11.
2. Скопіювати папку `backend/` (через SCP, GitHub Release zip, або git clone).
3. У PowerShell:
   ```powershell
   cd backend
   python -m venv .venv
   .venv\Scripts\pip install -e .
   ```
4. Встановити як Windows-службу через [NSSM](https://nssm.cc):
   ```powershell
   nssm install KasaReconBackend "C:\path\to\backend\.venv\Scripts\uvicorn.exe" `
     recon_backend.main:app --host 0.0.0.0 --port 8000
   nssm start KasaReconBackend
   ```

## Конфігурація 1С OData

У Конфігураторі 1С УНФ:
1. **Адміністрування → Налаштування публікації на веб-сервері**
2. Закладка «Загальні» → постав ☑️ «Публикация стандартного интерфейса OData»
3. Перепублікувати

Перевірка: `http://1c-server/<база>/odata/standard.odata/$metadata` має повернути XML.

## Стан розробки

- ✅ Алгоритм матчингу (точний + fuzzy + пересорт між касами, вікно 14 днів)
- ✅ Парсери: Privat24 Business CSV (юр.особа), УНФ звіт «Движение денег», УНФ журнал
- ✅ FastAPI бекенд з SQLite + 21 endpoint
- ✅ Flutter Desktop UI (Windows + macOS) — 5 екранів
- ⏳ OData клієнт для 1С УНФ (read + write)
- ⏳ Privat24 Business API клієнт
- ⏳ Endpoint «провести в 1С через OData»
- ⏳ Pidrozdily + пропорційний розподіл витрат у UI

## Контекст

Бізнес — 3+ ФОПи, торгівля через Instagram. Понад 2 роки в УНФ велась каса з помилками:
не списувались затрати, пересорти приходів між касами різних людей. Каси в УНФ — це
довідник «Банковский счет, касса», де об'єднано і готівка, і банк-рахунки, і термінали.

Звірка має знайти ці помилки і дати юзеру в UI кнопку «провести в 1С».

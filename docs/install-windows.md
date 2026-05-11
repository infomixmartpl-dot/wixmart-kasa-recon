# Встановлення на Windows-сервер з 1С

Інструкція як отримати готовий додаток на сервер де крутиться 1С УНФ.

## Що тут є

| Що | Де крутиться |
|----|---------------|
| **Бекенд** (FastAPI на Python) | Windows-сервер з 1С — як служба |
| **Фронтенд** (.exe Flutter Desktop) | Той же сервер, або твій ноут — ходить до бекенду по HTTP |

## Крок 1. Скачати .exe з GitHub Release

Після кожного `git push` у `main` GitHub Actions автоматично збирає Windows-білд.
Заходиш по RDP на сервер → відкриваєш у браузері:

```
https://github.com/infomixmartpl-dot/wixmart-kasa-recon/actions
```

Найвищий run «Build Windows .exe» → внизу артефакт `kasa_recon-YYYYMMDD-XXXXXXX` →
скачуєш zip → розпаковуєш у `C:\Programs\KasaRecon\`.

Запускаєш `kasa_recon.exe` — додаток відкривається.

> **Для іменних релізів:** замість артефактів роби `git tag v0.1.0 && git push --tags` —
> GitHub зробить **Release** з красивим zip-ом у розділі Releases.

## Крок 2. Встановити Python 3.11 на сервер

1. Скачати з python.org/downloads → Python 3.11.x → Windows installer (64-bit).
2. У встановлювачі поставити галочку **«Add python.exe to PATH»**.
3. Перевірити: `python --version` → має показати `Python 3.11.x`.

## Крок 3. Розгорнути бекенд

У PowerShell на сервері:

```powershell
# Скачати код з GitHub
git clone https://github.com/infomixmartpl-dot/wixmart-kasa-recon.git C:\Programs\KasaReconBackend
cd C:\Programs\KasaReconBackend\backend

# Створити venv і встановити залежності
python -m venv .venv
.venv\Scripts\pip install -e .

# Перевірка що працює
.venv\Scripts\uvicorn recon_backend.main:app --port 8000
```

Якщо `curl http://localhost:8000/health` повертає `{"status":"ok"}` — бекенд жвавий.

## Крок 4. Зробити бекенд службою Windows (через NSSM)

Щоб бекенд автоматично стартував з системою:

1. Скачати [NSSM](https://nssm.cc/download) → розпакувати → покласти `nssm.exe` у `C:\Programs\nssm\`.
2. У PowerShell **від адміністратора**:

```powershell
$NSSM = "C:\Programs\nssm\nssm.exe"
$APP_DIR = "C:\Programs\KasaReconBackend\backend"

& $NSSM install KasaReconBackend `
  "$APP_DIR\.venv\Scripts\python.exe" `
  "-m uvicorn recon_backend.main:app --host 0.0.0.0 --port 8000"

& $NSSM set KasaReconBackend AppDirectory "$APP_DIR"
& $NSSM set KasaReconBackend Start SERVICE_AUTO_START
& $NSSM start KasaReconBackend
```

Перевірити:
```powershell
Get-Service KasaReconBackend       # має бути Running
curl http://localhost:8000/health  # має бути ok
```

Зупинити/запустити пізніше:
```powershell
Stop-Service KasaReconBackend
Start-Service KasaReconBackend
```

## Крок 5. Налаштувати фронтенд

Запускаєш `kasa_recon.exe` на сервері (або на ноуті — якщо сервер видно по мережі).

На стартовому екрані додай ФОПа. У форму OData введи:
- **OData base URL**: `http://localhost/<твоя_база>/odata/standard.odata` (якщо ставив на тому ж сервері)
- **Login** і **Password** — від користувача 1С з повними правами

Зараз backend ще не використовує OData (поки нема клієнта). Це для майбутнього кроку.

## Як оновити версію

Просто:
```powershell
cd C:\Programs\KasaReconBackend
git pull
.venv\Scripts\pip install -e .\backend
Restart-Service KasaReconBackend
```

А фронтенд — скачай новий zip артефакт з GitHub Actions, перезапиши `kasa_recon.exe`.

## Troubleshooting

**`flutter analyze` падає на GHA з помилкою на CI?** Скоріше за все нова версія
Flutter не підтримує deprecated API. Локально пересоберись:
```bash
cd frontend && flutter pub upgrade && flutter analyze
```

**Бекенд не стартує — `ModuleNotFoundError`?** Перевір що `.venv\Scripts\pip install -e .` виконувався з папки `backend/`, не з кореня.

**Flutter додаток показує помилку «зв'язок з сервером»?** Перевір що бекенд відповідає:
```powershell
curl http://localhost:8000/health
```
Якщо ні — `Get-Service KasaReconBackend`, можливо служба впала.

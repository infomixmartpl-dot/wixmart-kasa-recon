"""Бекенд звірки ПриватБанк ↔ Каса 1С (УНФ 1.6).

Модулі:
- api     — FastAPI ендпоінти (CRUD, sync, recon, post)
- core    — алгоритм матчингу і пропорційного розподілу (перенесено з CLI)
- clients — клієнти зовнішніх API (Privat24 Business, 1С OData)
- db      — SQLAlchemy моделі і сесії
"""

__version__ = "0.1.0"

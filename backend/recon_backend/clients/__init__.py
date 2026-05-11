"""Клієнти зовнішніх API: 1С OData, Privat24 Business."""
from .odata_1c import OData1CClient, OData1CError

__all__ = ["OData1CClient", "OData1CError"]

"""Репозитории доступа к данным."""

from database.repositories.base import BaseRepository
from database.repositories.lead_repo import LeadRepository
from database.repositories.license_repo import LicenseRepository

__all__ = ["BaseRepository", "LeadRepository", "LicenseRepository"]

"""Environment configuration for JALUR API."""
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    session_pepper: str = os.getenv("SESSION_PEPPER", "")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5500")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "12"))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    directory_data_path: str = str((PROJECT_ROOT / os.getenv("JALUR_DIRECTORY_FILE", "data/database.js")).resolve())
    cors_origins: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("CORS_ORIGINS", os.getenv("FRONTEND_ORIGIN", "http://localhost:5500")).split(",") if x.strip()
    )

settings = Settings()

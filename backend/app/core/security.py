"""Security helpers; compatible with bcrypt hashes from the original Node service."""
import base64, hashlib, secrets
import bcrypt
from .config import settings

def digest(value: str) -> str:
    if not settings.session_pepper:
        raise RuntimeError("SESSION_PEPPER belum dikonfigurasi.")
    return hashlib.sha256(f"{settings.session_pepper}:{value}".encode()).hexdigest()

def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False

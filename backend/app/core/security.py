import secrets
from hashlib import sha256

from passlib.context import CryptContext


password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, stored_password: str | None) -> bool:
    if not stored_password:
        return False

    # Keep old demo accounts usable if they were created before real hashing.
    if stored_password.endswith("_hashed"):
        return secrets.compare_digest(stored_password, f"{password}_hashed")

    try:
        return password_context.verify(password, stored_password)
    except (TypeError, ValueError):
        return False


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()

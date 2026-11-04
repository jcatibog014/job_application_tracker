"""Encrypting Gmail app passwords before they go into the database.

Fernet (from the cryptography library) encrypts and signs, so a changed
value can't be read either. Its key comes from ENCRYPTION_KEY (any long
random text; Render makes one), turned into the 32 bytes Fernet wants.
Locally, without ENCRYPTION_KEY, it is made from SECRET_KEY instead.

If the key ever changes, stored passwords can't be read any more:
decrypt() returns None and the person connects Gmail again.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet():
    secret = current_app.config.get("ENCRYPTION_KEY") or current_app.config["SECRET_KEY"]
    key = hashlib.sha256(b"hirewire-gmail:" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(text):
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None

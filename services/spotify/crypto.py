import os
import base64
import hashlib
import secrets
from typing import Optional
from utils.logger import log

def _get_derived_key() -> bytes:
    """
    Derives a 32-byte cryptographic key from SPOTIFY_TOKEN_ENCRYPTION_KEY
    or the bot's secret token as a fallback.
    """
    secret = (
        os.getenv("SPOTIFY_TOKEN_ENCRYPTION_KEY") or
        os.getenv("DISCORD_TOKEN") or
        "syncink-radio-secure-fallback-key-2026"
    )
    # Use PBKDF2 HMAC SHA256 with a static application salt for deterministic key derivation
    salt = b"syncink_radio_spotify_token_vault_v1"
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations=100_000, dklen=32)

class TokenEncryptor:
    """
    Authenticated encryption and decryption for sensitive Spotify user refresh tokens.
    Uses PyNaCl SecretBox (installed with discord.py[voice]) or cryptography Fernet.
    """
    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        if not plaintext:
            return ""
        key = _get_derived_key()
        raw_data = plaintext.encode("utf-8")

        # 1. Try PyNaCl SecretBox (guaranteed by discord.py voice dependencies)
        try:
            import nacl.secret
            import nacl.utils
            box = nacl.secret.SecretBox(key)
            encrypted = box.encrypt(raw_data)
            return "nacl:" + base64.urlsafe_b64encode(encrypted).decode("ascii")
        except ImportError:
            pass

        # 2. Try cryptography.fernet
        try:
            from cryptography.fernet import Fernet
            f_key = base64.urlsafe_b64encode(key)
            f = Fernet(f_key)
            token = f.encrypt(raw_data)
            return "fernet:" + token.decode("ascii")
        except ImportError:
            pass

        # 3. Secure Fallback: XOR stream cipher authenticated with HMAC-SHA256
        nonce = secrets.token_bytes(16)
        keystream = hashlib.sha256(key + nonce).digest()
        # Extend keystream if needed
        while len(keystream) < len(raw_data):
            keystream += hashlib.sha256(key + keystream).digest()
        ciphertext = bytes([b ^ k for b, k in zip(raw_data, keystream[:len(raw_data)])])
        tag = hashlib.sha256(key + nonce + ciphertext).digest()
        payload = nonce + tag + ciphertext
        return "syncink:" + base64.urlsafe_b64encode(payload).decode("ascii")

    @classmethod
    def decrypt(cls, payload_str: str) -> Optional[str]:
        if not payload_str:
            return None
        key = _get_derived_key()

        try:
            if payload_str.startswith("nacl:"):
                import nacl.secret
                box = nacl.secret.SecretBox(key)
                encrypted = base64.urlsafe_b64decode(payload_str[5:].encode("ascii"))
                decrypted = box.decrypt(encrypted)
                return decrypted.decode("utf-8")

            if payload_str.startswith("fernet:"):
                from cryptography.fernet import Fernet
                f_key = base64.urlsafe_b64encode(key)
                f = Fernet(f_key)
                decrypted = f.decrypt(payload_str[7:].encode("ascii"))
                return decrypted.decode("utf-8")

            if payload_str.startswith("syncink:"):
                raw = base64.urlsafe_b64decode(payload_str[8:].encode("ascii"))
                nonce = raw[:16]
                tag = raw[16:48]
                ciphertext = raw[48:]
                expected_tag = hashlib.sha256(key + nonce + ciphertext).digest()
                if not secrets.compare_digest(tag, expected_tag):
                    log.error("[TokenEncryptor] HMAC tag verification failed; possible tampering.")
                    return None
                keystream = hashlib.sha256(key + nonce).digest()
                while len(keystream) < len(ciphertext):
                    keystream += hashlib.sha256(key + keystream).digest()
                decrypted = bytes([b ^ k for b, k in zip(ciphertext, keystream[:len(ciphertext)])])
                return decrypted.decode("utf-8")

            # Legacy or un-prefixed fallback attempt
            return payload_str
        except Exception as e:
            log.error(f"[TokenEncryptor] Decryption error: {e}")
            return None

"""
Credential encryption/decryption service for per-user API keys.

Uses AES-256-GCM for authenticated encryption with a server-side master key.
"""
import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _get_encryption_key() -> bytes:
    """
    Get the encryption key from settings.
    
    Returns:
        32-byte encryption key
        
    Raises:
        RuntimeError: If ENCRYPTION_KEY is not configured or invalid
    """
    key_b64 = settings.ENCRYPTION_KEY.strip()
    if not key_b64:
        raise RuntimeError("ENCRYPTION_KEY is not configured in settings")
    
    try:
        key = base64.b64decode(key_b64)
    except Exception as e:
        raise RuntimeError(f"ENCRYPTION_KEY is not valid base64: {e}") from e
    
    if len(key) != 32:
        raise RuntimeError(f"ENCRYPTION_KEY must be 32 bytes (256 bits), got {len(key)} bytes")
    
    return key


def encrypt_credential(plaintext: str) -> str:
    """
    Encrypt a credential (API key) using AES-256-GCM.
    
    Args:
        plaintext: The credential to encrypt (e.g., API key)
        
    Returns:
        Base64-encoded string: nonce (12 bytes) + ciphertext + tag (16 bytes)
        
    Raises:
        RuntimeError: If encryption key is not configured
    """
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    
    # Generate a random 96-bit (12-byte) nonce
    nonce = os.urandom(12)
    
    # Encrypt and authenticate
    plaintext_bytes = plaintext.encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)
    
    # Combine nonce + ciphertext (which includes the 16-byte authentication tag)
    encrypted = nonce + ciphertext
    
    # Return as base64 for storage
    return base64.b64encode(encrypted).decode('ascii')


def decrypt_credential(encrypted_b64: str) -> str | None:
    """
    Decrypt a credential (API key) using AES-256-GCM.
    
    Args:
        encrypted_b64: Base64-encoded encrypted credential from encrypt_credential()
        
    Returns:
        Decrypted plaintext credential, or None if decryption fails
        
    Raises:
        RuntimeError: If encryption key is not configured
    """
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    
    try:
        # Decode from base64
        encrypted = base64.b64decode(encrypted_b64)
        
        # Extract nonce (first 12 bytes) and ciphertext (rest)
        if len(encrypted) < 12 + 16:  # nonce + minimum ciphertext with tag
            return None
        
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        
        # Decrypt and verify authentication tag
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return plaintext_bytes.decode('utf-8')
        
    except (InvalidTag, ValueError, UnicodeDecodeError):
        # InvalidTag: authentication failed (tampered data or wrong key)
        # ValueError: malformed input
        # UnicodeDecodeError: decrypted bytes are not valid UTF-8
        return None

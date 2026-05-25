"""File-based secrets management with Fernet encryption"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
import structlog

logger = structlog.get_logger()


class SecretsManager:
    """File-based secrets manager with Fernet encryption"""
    
    def __init__(self, secrets_file: str = "secrets.enc", key_file: str = ".secrets_key"):
        self.secrets_file = Path(secrets_file)
        self.key_file = Path(key_file)
        self._fernet: Optional[Fernet] = None
        self._secrets: Dict[str, Any] = {}
        self._load_or_create_key()
        self._load_secrets()
    
    def _load_or_create_key(self):
        """Load existing encryption key or create a new one"""
        if self.key_file.exists():
            with open(self.key_file, 'rb') as f:
                key = f.read()
            self._fernet = Fernet(key)
            logger.info("secrets_key_loaded")
        else:
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)
            self._fernet = Fernet(key)
            logger.info("secrets_key_created")
    
    def _load_secrets(self):
        """Load and decrypt secrets from file"""
        if self.secrets_file.exists():
            try:
                with open(self.secrets_file, 'rb') as f:
                    encrypted_data = f.read()
                decrypted_data = self._fernet.decrypt(encrypted_data)
                self._secrets = json.loads(decrypted_data.decode())
                logger.info("secrets_loaded", count=len(self._secrets))
            except Exception as e:
                logger.error("secrets_load_failed", error=str(e))
                self._secrets = {}
        else:
            self._secrets = {}
            logger.info("secrets_file_not_found", file=str(self.secrets_file))
    
    def _save_secrets(self):
        """Encrypt and save secrets to file"""
        try:
            data = json.dumps(self._secrets).encode()
            encrypted_data = self._fernet.encrypt(data)
            with open(self.secrets_file, 'wb') as f:
                f.write(encrypted_data)
            # Set restrictive permissions
            os.chmod(self.secrets_file, 0o600)
            logger.info("secrets_saved", count=len(self._secrets))
        except Exception as e:
            logger.error("secrets_save_failed", error=str(e))
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a secret value"""
        return self._secrets.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a secret value"""
        self._secrets[key] = value
        self._save_secrets()
        logger.info("secret_set", key=key)
    
    def delete(self, key: str):
        """Delete a secret"""
        if key in self._secrets:
            del self._secrets[key]
            self._save_secrets()
            logger.info("secret_deleted", key=key)
    
    def list_keys(self) -> list:
        """List all secret keys"""
        return list(self._secrets.keys())
    
    def exists(self, key: str) -> bool:
        """Check if a secret exists"""
        return key in self._secrets
    
    def get_all(self) -> Dict[str, Any]:
        """Get all secrets (use with caution)"""
        return self._secrets.copy()
    
    def rotate_key(self):
        """Rotate the encryption key and re-encrypt all secrets"""
        logger.info("secrets_key_rotation_started")
        
        # Save current secrets
        current_secrets = self._secrets.copy()
        
        # Generate new key
        new_key = Fernet.generate_key()
        with open(self.key_file, 'wb') as f:
            f.write(new_key)
        os.chmod(self.key_file, 0o600)
        
        # Update fernet instance
        self._fernet = Fernet(new_key)
        
        # Re-encrypt and save secrets
        self._secrets = current_secrets
        self._save_secrets()
        
        logger.info("secrets_key_rotation_completed")


# Global secrets manager instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get the global secrets manager instance"""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def get_secret(key: str, default: Any = None) -> Any:
    """Convenience function to get a secret"""
    return get_secrets_manager().get(key, default)


def set_secret(key: str, value: Any):
    """Convenience function to set a secret"""
    get_secrets_manager().set(key, value)


def delete_secret(key: str):
    """Convenience function to delete a secret"""
    get_secrets_manager().delete(key)

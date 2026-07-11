"""
ERP Security and Audit Logging

Security and audit logging framework for ERP integrations:
- All ERP data access logged to audit table
- Field-level encryption for sensitive fields
- Data masking in logs
- Multi-tenant data isolation
- API key scoping for ERP operations
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from cryptography.fernet import Fernet
import base64
import hashlib
import os

from app.core.config import settings

from app.db.models import AuditLog
from app.db.database import get_db

logger = structlog.get_logger()


class ERPSecurityManager:
    """
    Security manager for ERP integrations.
    
    Handles encryption, data masking, audit logging,
    and access control for ERP data.
    """
    
    # Sensitive fields that should be encrypted
    SENSITIVE_FIELDS = {
        "credit_card",
        "ssn",
        "social_security",
        "bank_account",
        "password",
        "api_key",
        "secret",
        "token",
        "auth_token",
        "access_token",
        "refresh_token"
    }
    
    # Fields that should be masked in logs
    MASKED_FIELDS = {
        "email",
        "phone",
        "address",
        "name",
        "username",
        "customer_id",
        "vendor_id",
        "employee_id"
    }
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self._encryption_key = self._get_or_create_encryption_key()
        self._cipher = Fernet(self._encryption_key)
        
        logger.info(
            "security_manager_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get or create encryption key for the organization.
        
        Returns:
            bytes: Encryption key
        """
        # 1) Explicit per-org key via env (highest precedence, back-compat).
        explicit = os.getenv(f"ERP_ENCRYPTION_KEY_{self.organization_id}")
        if explicit:
            return explicit.encode()

        # 2) Derive a STABLE per-org key from the master key. Deterministic, so
        #    it survives restarts (a random runtime key would make previously-
        #    encrypted credentials undecryptable — the bug this replaces).
        master = settings.ERP_ENCRYPTION_KEY
        if not master:
            # Dev-only fallback: still deterministic (not random), so local data
            # round-trips. Production startup fails via validate_settings when
            # ERP_ENCRYPTION_KEY is unset, so this path is dev-only.
            master = "dev-insecure-erp-master-key"
            logger.warning(
                "erp_encryption_key_dev_fallback",
                organization_id=self.organization_id,
                message="ERP_ENCRYPTION_KEY unset; using an insecure dev-only derived key",
            )
        digest = hashlib.sha256(f"{master}:{self.organization_id}".encode()).digest()
        return base64.urlsafe_b64encode(digest)
    
    def encrypt_field(self, value: str) -> str:
        """
        Encrypt a sensitive field value.
        
        Args:
            value: Value to encrypt
            
        Returns:
            str: Encrypted value
        """
        if not value:
            return value
        
        encrypted = self._cipher.encrypt(value.encode())
        return encrypted.decode()
    
    def decrypt_field(self, encrypted_value: str) -> str:
        """
        Decrypt a sensitive field value.
        
        Args:
            encrypted_value: Encrypted value
            
        Returns:
            str: Decrypted value
        """
        if not encrypted_value:
            return encrypted_value
        
        try:
            decrypted = self._cipher.decrypt(encrypted_value.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(
                "decryption_failed",
                error=str(e)
            )
            return encrypted_value
    
    def encrypt_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encrypt sensitive fields in data dictionary.
        
        Args:
            data: Data dictionary
            
        Returns:
            Dict with sensitive fields encrypted
        """
        encrypted_data = data.copy()
        
        for key, value in data.items():
            if key.lower() in self.SENSITIVE_FIELDS and isinstance(value, str):
                encrypted_data[key] = self.encrypt_field(value)
        
        return encrypted_data
    
    def decrypt_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decrypt sensitive fields in data dictionary.
        
        Args:
            data: Data dictionary
            
        Returns:
            Dict with sensitive fields decrypted
        """
        decrypted_data = data.copy()
        
        for key, value in data.items():
            if key.lower() in self.SENSITIVE_FIELDS and isinstance(value, str):
                decrypted_data[key] = self.decrypt_field(value)
        
        return decrypted_data
    
    def mask_data_for_logging(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mask sensitive fields for logging.
        
        Args:
            data: Data dictionary
            
        Returns:
            Dict with sensitive fields masked
        """
        masked_data = data.copy()
        
        for key, value in data.items():
            if key.lower() in self.MASKED_FIELDS and isinstance(value, str):
                # Mask all but first and last character
                if len(value) > 2:
                    masked_data[key] = value[0] + "*" * (len(value) - 2) + value[-1]
                else:
                    masked_data[key] = "*" * len(value)
        
        return masked_data
    
    async def log_audit_event(
        self,
        db: AsyncSession,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        user_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ):
        """
        Log an audit event for ERP data access.
        
        Args:
            db: Database session
            action: Action performed (read, write, delete, etc.)
            resource_type: Type of resource accessed
            resource_id: ID of resource
            user_id: User who performed the action
            details: Additional details
            ip_address: IP address of the request
        """
        # Mask sensitive data in details
        masked_details = None
        if details:
            masked_details = self.mask_data_for_logging(details)
        
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=self.organization_id,
            details=masked_details,
            ip_address=ip_address,
            created_at=datetime.utcnow()
        )
        
        db.add(audit_log)
        await db.commit()
        
        logger.info(
            "audit_event_logged",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id
        )
    
    def check_api_key_scope(
        self,
        api_key_scopes: List[str],
        required_scope: str
    ) -> bool:
        """
        Check if API key has required scope for ERP operation.
        
        Args:
            api_key_scopes: Scopes assigned to API key
            required_scope: Required scope for operation
            
        Returns:
            bool: True if key has required scope
        """
        # ERP-specific scopes
        erp_scopes = [
            "erp:read",
            "erp:write",
            "erp:admin",
            "erp:sap:read",
            "erp:sap:write",
            "erp:oracle:read",
            "erp:oracle:write",
            "erp:dynamics:read",
            "erp:dynamics:write"
        ]
        
        # Check for exact match
        if required_scope in api_key_scopes:
            return True
        
        # Check for admin scope (grants all access)
        if "erp:admin" in api_key_scopes:
            return True
        
        # Check for broader scope (e.g., erp:read grants erp:sap:read)
        if required_scope in erp_scopes:
            base_scope = required_scope.split(":")[0] + ":" + required_scope.split(":")[1]
            if base_scope in api_key_scopes:
                return True
        
        return False
    
    def validate_organization_access(
        self,
        user_organization_id: str,
        resource_organization_id: str
    ) -> bool:
        """
        Validate that user has access to organization's ERP data.
        
        Args:
            user_organization_id: User's organization ID
            resource_organization_id: Resource's organization ID
            
        Returns:
            bool: True if user has access
        """
        return user_organization_id == resource_organization_id
    
    async def get_audit_trail(
        self,
        db: AsyncSession,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail for ERP operations.
        
        Args:
            db: Database session
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            user_id: Filter by user ID
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum number of records
            
        Returns:
            List of audit log entries
        """
        from sqlalchemy import and_, or_
        
        query = select(AuditLog).where(
            AuditLog.organization_id == self.organization_id
        )
        
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        
        if start_date:
            query = query.where(AuditLog.created_at >= start_date)
        
        if end_date:
            query = query.where(AuditLog.created_at <= end_date)
        
        query = query.order_by(AuditLog.created_at.desc()).limit(limit)
        
        result = await db.execute(query)
        audit_logs = result.scalars().all()
        
        return [
            {
                "id": str(log.id),
                "user_id": str(log.user_id),
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat()
            }
            for log in audit_logs
        ]


class ERPDataGovernance:
    """
    Data governance for ERP integrations.
    
    Handles data classification, retention policies,
    and privacy compliance.
    """
    
    DATA_CLASSIFICATIONS = {
        "public": "Data that can be freely shared",
        "internal": "Data for internal use only",
        "confidential": "Sensitive data requiring access controls",
        "restricted": "Highly sensitive data with strict controls"
    }
    
    def __init__(self, organization_id: str):
        self.organization_id = organization_id
        
        logger.info(
            "data_governance_initialized",
            organization_id=organization_id
        )
    
    def classify_data(self, data: Dict[str, Any]) -> str:
        """
        Classify data based on sensitivity.
        
        Args:
            data: Data dictionary
            
        Returns:
            str: Data classification
        """
        # Check for restricted data
        restricted_fields = {"credit_card", "ssn", "bank_account"}
        for field in restricted_fields:
            if field in data or field.replace("_", "") in data:
                return "restricted"
        
        # Check for confidential data
        confidential_fields = {"salary", "compensation", "contract"}
        for field in confidential_fields:
            if field in data or field.replace("_", "") in data:
                return "confidential"
        
        # Check for internal data
        internal_fields = {"employee_id", "vendor_id", "customer_id"}
        for field in internal_fields:
            if field in data or field.replace("_", "") in data:
                return "internal"
        
        # Default to public
        return "public"
    
    def apply_retention_policy(
        self,
        data_classification: str,
        data_age_days: int
    ) -> bool:
        """
        Check if data should be retained based on retention policy.
        
        Args:
            data_classification: Classification of data
            data_age_days: Age of data in days
            
        Returns:
            bool: True if data should be retained
        """
        retention_policies = {
            "public": 365 * 7,  # 7 years
            "internal": 365 * 5,  # 5 years
            "confidential": 365 * 3,  # 3 years
            "restricted": 365 * 1  # 1 year
        }
        
        retention_days = retention_policies.get(data_classification, 365)
        
        return data_age_days <= retention_days
    
    async def log_data_access(
        self,
        db: AsyncSession,
        data_classification: str,
        access_type: str,
        user_id: str,
        resource_id: str
    ):
        """
        Log data access for compliance tracking.
        
        Args:
            db: Database session
            data_classification: Classification of data accessed
            access_type: Type of access (read, write, delete)
            user_id: User who accessed data
            resource_id: ID of resource accessed
        """
        # This could be integrated with the audit log system
        logger.info(
            "data_access_logged",
            classification=data_classification,
            access_type=access_type,
            user_id=user_id,
            resource_id=resource_id
        )

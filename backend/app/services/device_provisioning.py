"""
Zero-Trust Device Provisioning Service
Manages mTLS certificates for edge devices with cryptographic identity
"""

import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import structlog
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.core.config import settings

logger = structlog.get_logger()


class DeviceStatus(Enum):
    PENDING = "pending"      # Awaiting approval
    APPROVED = "approved"    # Active and authenticated
    SUSPENDED = "suspended"  # Temporarily blocked
    REVOKED = "revoked"      # Permanently blocked


@dataclass
class DeviceIdentity:
    """Cryptographic device identity"""
    device_id: str
    asset_id: Optional[str]
    device_type: str  # 'bambu_collector', 'qidi_collector', etc.
    certificate_pem: str
    private_key_pem: Optional[str]  # Only stored during initial provisioning
    fingerprint: str  # SHA256 of certificate
    issued_at: datetime
    expires_at: datetime
    status: DeviceStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None
    last_seen: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)


class CertificateAuthority:
    """
    Local Certificate Authority for zero-trust device provisioning.
    Issues and revokes device certificates.
    """
    
    def __init__(self, ca_cert_path: str = None, ca_key_path: str = None):
        self.ca_cert_path = ca_cert_path or settings.MTLS_CA_CERT_PATH
        self.ca_key_path = ca_key_path or settings.CA_KEY_PATH or '/certs/ca.key'
        self.crl_path = settings.CRL_PATH or '/certs/ca.crl'
        
        self._ca_cert: Optional[x509.Certificate] = None
        self._ca_key = None
        self._load_ca()
    
    def _load_ca(self):
        """Load CA certificate and key"""
        try:
            with open(self.ca_cert_path, 'rb') as f:
                self._ca_cert = x509.load_pem_x509_certificate(f.read())
            
            with open(self.ca_key_path, 'rb') as f:
                self._ca_key = serialization.load_pem_private_key(f.read(), password=None)
                
            logger.info("ca_loaded", 
                       subject=self._ca_cert.subject.rfc4514_string(),
                       not_after=self._ca_cert.not_valid_after)
        except Exception as e:
            logger.error("ca_load_failed", error=str(e))
            # Will generate new CA on first provision
    
    def _generate_ca(self) -> (x509.Certificate, rsa.RSAPrivateKey):
        """Generate new CA certificate if none exists"""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpsGrid"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Manufacturing IoT"),
            x509.NameAttribute(NameOID.COMMON_NAME, "OpsGrid Device CA"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=3650)  # 10 years
        ).add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        ).sign(private_key, hashes.SHA256())
        
        return cert, private_key
    
    async def issue_certificate(self, 
                                device_type: str,
                                asset_id: Optional[str] = None,
                                device_metadata: Dict = None) -> DeviceIdentity:
        """Issue new device certificate"""
        
        # Generate device key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Generate device ID
        device_id = f"{device_type}-{uuid.uuid4().hex[:8]}"
        
        # Create CSR subject
        subject = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpsGrid"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, device_type),
            x509.NameAttribute(NameOID.COMMON_NAME, device_id),
        ])
        
        # Build certificate
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            self._ca_cert.subject
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=365)  # 1 year validity
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(f"{device_id}.opsgrid.local"),
            ]),
            critical=False,
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                data_encipherment=False,
                key_cert_sign=False,
                crl_sign=False,
            ),
            critical=True,
        ).add_extension(
            x509.ExtendedKeyUsage([
                x509.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        ).sign(self._ca_key, hashes.SHA256())
        
        # Serialize
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode()
        
        # Calculate fingerprint
        fingerprint = hashlib.sha256(
            cert.public_bytes(serialization.Encoding.DER)
        ).hexdigest()
        
        device = DeviceIdentity(
            device_id=device_id,
            asset_id=asset_id,
            device_type=device_type,
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            fingerprint=fingerprint,
            issued_at=datetime.utcnow(),
            expires_at=cert.not_valid_after,
            status=DeviceStatus.PENDING,
            metadata=device_metadata or {}
        )
        
        # Persist to database
        await self._persist_device(device)
        
        logger.info("certificate_issued",
                   device_id=device_id,
                   fingerprint=fingerprint[:16])
        
        return device
    
    async def _persist_device(self, device: DeviceIdentity):
        """Store device identity in database"""
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(f"""
                    INSERT INTO device_identities (
                        device_id, asset_id, device_type, certificate_pem,
                        fingerprint, issued_at, expires_at, status, metadata
                    ) VALUES (
                        '{device.device_id}',
                        '{device.asset_id or ''}',
                        '{device.device_type}',
                        '{device.certificate_pem}',
                        '{device.fingerprint}',
                        '{device.issued_at.isoformat()}',
                        '{device.expires_at.isoformat()}',
                        '{device.status.value}',
                        '{json.dumps(device.metadata)}'
                    )
                    ON CONFLICT (device_id) DO UPDATE SET
                        certificate_pem = EXCLUDED.certificate_pem,
                        fingerprint = EXCLUDED.fingerprint,
                        issued_at = EXCLUDED.issued_at,
                        expires_at = EXCLUDED.expires_at,
                        status = EXCLUDED.status
                """)
            )
            await session.commit()
    
    async def approve_device(self, 
                             device_id: str, 
                             approver: str) -> bool:
        """Approve pending device certificate"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    UPDATE device_identities
                    SET status = 'approved',
                        approved_by = '{approver}',
                        approved_at = '{datetime.utcnow().isoformat()}'
                    WHERE device_id = '{device_id}'
                      AND status = 'pending'
                    RETURNING device_id
                """)
            )
            
            if result.fetchone():
                await session.commit()
                logger.info("device_approved", 
                           device_id=device_id, 
                           approver=approver)
                return True
            
            return False
    
    async def revoke_certificate(self, 
                                 device_id: str, 
                                 reason: str,
                                 revoked_by: str) -> bool:
        """
        Revoke device certificate immediately.
        Device will be blocked from all communication.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    UPDATE device_identities
                    SET status = 'revoked',
                        revoked_at = '{datetime.utcnow().isoformat()}',
                        revoked_reason = '{reason}'
                    WHERE device_id = '{device_id}'
                      AND status != 'revoked'
                    RETURNING device_id
                """)
            )
            
            if result.fetchone():
                await session.commit()
                
                # Update CRL
                await self._update_crl()
                
                logger.warning("certificate_revoked",
                            device_id=device_id,
                            reason=reason,
                            revoked_by=revoked_by)
                return True
            
            return False
    
    async def _update_crl(self):
        """Update Certificate Revocation List"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("""
                    SELECT fingerprint, revoked_at
                    FROM device_identities
                    WHERE status = 'revoked'
                """)
            )
            
            revoked_certs = result.all()
            # Build and save CRL
            # Implementation details omitted for brevity
            
    async def verify_certificate(self, fingerprint: str) -> Optional[DeviceIdentity]:
        """Verify certificate fingerprint and return device identity"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    SELECT device_id, asset_id, device_type, certificate_pem,
                           fingerprint, issued_at, expires_at, status,
                           approved_by, approved_at, revoked_at, revoked_reason,
                           metadata
                    FROM device_identities
                    WHERE fingerprint = '{fingerprint}'
                """)
            )
            
            row = result.fetchone()
            if not row:
                return None
            
            # Check expiration
            expires_at = row[6]
            if expires_at < datetime.utcnow():
                logger.warning("certificate_expired", 
                              fingerprint=fingerprint[:16])
                return None
            
            # Check status
            status = DeviceStatus(row[7])
            if status != DeviceStatus.APPROVED:
                logger.warning("certificate_not_approved",
                              fingerprint=fingerprint[:16],
                              status=status.value)
                return None
            
            return DeviceIdentity(
                device_id=row[0],
                asset_id=row[1],
                device_type=row[2],
                certificate_pem=row[3],
                private_key_pem=None,  # Never return private key
                fingerprint=row[4],
                issued_at=row[5],
                expires_at=expires_at,
                status=status,
                approved_by=row[8],
                approved_at=row[9],
                revoked_at=row[10],
                revoked_reason=row[11],
                metadata=json.loads(row[12]) if row[12] else {}
            )
    
    async def list_devices(self, 
                          status: Optional[DeviceStatus] = None) -> List[DeviceIdentity]:
        """List all registered devices"""
        query = "SELECT device_id FROM device_identities"
        if status:
            query += f" WHERE status = '{status.value}'"
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(query))
            device_ids = [row[0] for row in result]
        
        devices = []
        for device_id in device_ids:
            # Get full device details
            device = await self.get_device(device_id)
            if device:
                devices.append(device)
        
        return devices
    
    async def get_device(self, device_id: str) -> Optional[DeviceIdentity]:
        """Get device by ID"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    SELECT * FROM device_identities
                    WHERE device_id = '{device_id}'
                """)
            )
            row = result.fetchone()
            
            if not row:
                return None
            
            # Convert to DeviceIdentity
            return DeviceIdentity(
                device_id=row[0],
                asset_id=row[1],
                device_type=row[2],
                certificate_pem=row[3],
                private_key_pem=None,
                fingerprint=row[5],
                issued_at=row[6],
                expires_at=row[7],
                status=DeviceStatus(row[8]),
                approved_by=row[9],
                approved_at=row[10],
                revoked_at=row[11],
                revoked_reason=row[12],
                metadata=json.loads(row[14]) if row[14] else {}
            )


# Global CA instance
ca = CertificateAuthority()
import json

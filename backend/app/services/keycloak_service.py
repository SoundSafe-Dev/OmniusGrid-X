"""Keycloak Identity Provider Integration Service"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from fastapi import HTTPException, status
try:
    from keycloak import KeycloakOpenID, KeycloakAdmin
    from keycloak.exceptions import KeycloakError
except ImportError:
    # Keycloak not installed - service will be disabled
    KeycloakOpenID = None
    KeycloakAdmin = None
    KeycloakError = Exception
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class KeycloakService:
    """Service for Keycloak identity provider integration."""
    
    def __init__(self):
        if KeycloakOpenID is None or KeycloakAdmin is None:
            raise RuntimeError("python-keycloak is not installed")

        self.keycloak_url: str = settings.KEYCLOAK_URL.rstrip("/")
        self.realm: str = settings.KEYCLOAK_REALM
        self.client_id: str = settings.KEYCLOAK_CLIENT_ID
        self.client_secret: str = settings.KEYCLOAK_CLIENT_SECRET
        
        # Initialize Keycloak OpenID client for authentication
        self.keycloak_openid = KeycloakOpenID(
            server_url=self.keycloak_url,
            client_id=self.client_id,
            client_secret_key=self.client_secret,
            realm_name=self.realm,
            verify=True
        )
        
        # Admin client is built lazily: token validation only needs the OpenID
        # client, so admin credentials are not required just to verify tokens.
        self._keycloak_admin: Optional["KeycloakAdmin"] = None

    @property
    def keycloak_admin(self) -> "KeycloakAdmin":
        """Lazily construct the Keycloak Admin client (requires admin creds)."""
        if self._keycloak_admin is None:
            self._keycloak_admin = KeycloakAdmin(
                server_url=self.keycloak_url,
                username=settings.KEYCLOAK_ADMIN_USERNAME,
                password=settings.KEYCLOAK_ADMIN_PASSWORD,
                realm_name=self.realm,
                verify=True
            )
        return self._keycloak_admin

    async def get_token(self, username: str, password: str) -> Dict[str, Any]:
        """
        Get JWT token from Keycloak for user authentication.
        
        Args:
            username: User's username
            password: User's password
            
        Returns:
            Dictionary containing access token, refresh token, etc.
            
        Raises:
            HTTPException: If authentication fails
        """
        try:
            token_info = self.keycloak_openid.token(
                username=username,
                password=password
            )
            
            logger.info(
                "keycloak_auth_success",
                username=username,
                realm=self.realm
            )
            
            return token_info
            
        except KeycloakError as e:
            logger.error(
                "keycloak_auth_failed",
                username=username,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
    
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Refresh token from previous authentication
            
        Returns:
            Dictionary containing new access token and refresh token
        """
        try:
            token_info = self.keycloak_openid.refresh_token(
                refresh_token=refresh_token
            )
            
            logger.info("keycloak_token_refreshed")
            
            return token_info
            
        except KeycloakError as e:
            logger.error("keycloak_token_refresh_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token refresh failed"
            )
    
    async def logout(self, refresh_token: str) -> None:
        """
        Logout user by invalidating refresh token.
        
        Args:
            refresh_token: Refresh token to invalidate
        """
        try:
            self.keycloak_openid.logout(refresh_token)
            logger.info("keycloak_logout_success")
            
        except KeycloakError as e:
            logger.error("keycloak_logout_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Logout failed"
            )
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user information from Keycloak using access token.
        
        Args:
            access_token: Valid JWT access token
            
        Returns:
            Dictionary containing user information
        """
        try:
            user_info = self.keycloak_openid.userinfo(token=access_token)
            logger.info("keycloak_user_info_retrieved", username=user_info.get('username'))
            return user_info
            
        except KeycloakError as e:
            logger.error("keycloak_user_info_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to retrieve user information"
            )
    
    async def create_user(
        self,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        organization_id: str,
        roles: Optional[List[str]] = None
    ) -> str:
        """
        Create a new user in Keycloak (JIT provisioning).
        
        Args:
            username: Unique username
            email: User's email address
            first_name: User's first name
            last_name: User's last name
            password: User's password
            organization_id: Organization ID for user
            roles: List of roles to assign
            
        Returns:
            User ID from Keycloak
        """
        try:
            user_data = {
                "username": username,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                "emailVerified": True,
                "credentials": [{
                    "type": "password",
                    "value": password,
                    "temporary": False
                }],
                "attributes": {
                    "organization_id": [organization_id]
                }
            }
            
            user_id = self.keycloak_admin.create_user(user_data)
            
            # Assign roles if provided
            if roles:
                await self.assign_roles(user_id, roles)
            
            logger.info(
                "keycloak_user_created",
                username=username,
                user_id=user_id,
                organization_id=organization_id
            )
            
            return user_id
            
        except KeycloakError as e:
            logger.error(
                "keycloak_user_creation_failed",
                username=username,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user in Keycloak"
            )
    
    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        enabled: Optional[bool] = None
    ) -> None:
        """
        Update user information in Keycloak.
        
        Args:
            user_id: Keycloak user ID
            email: New email address
            first_name: New first name
            last_name: New last name
            enabled: Enable/disable user account
        """
        try:
            user_data = {}
            
            if email is not None:
                user_data["email"] = email
            if first_name is not None:
                user_data["firstName"] = first_name
            if last_name is not None:
                user_data["lastName"] = last_name
            if enabled is not None:
                user_data["enabled"] = enabled
            
            if user_data:
                self.keycloak_admin.update_user(user_id, user_data)
                logger.info("keycloak_user_updated", user_id=user_id)
                
        except KeycloakError as e:
            logger.error(
                "keycloak_user_update_failed",
                user_id=user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user in Keycloak"
            )
    
    async def delete_user(self, user_id: str) -> None:
        """
        Delete user from Keycloak.
        
        Args:
            user_id: Keycloak user ID
        """
        try:
            self.keycloak_admin.delete_user(user_id)
            logger.info("keycloak_user_deleted", user_id=user_id)
            
        except KeycloakError as e:
            logger.error(
                "keycloak_user_deletion_failed",
                user_id=user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user from Keycloak"
            )
    
    async def assign_roles(self, user_id: str, roles: List[str]) -> None:
        """
        Assign roles to a user.
        
        Args:
            user_id: Keycloak user ID
            roles: List of role names to assign
        """
        try:
            # Get role representations
            role_reps = []
            for role_name in roles:
                role = self.keycloak_admin.get_realm_role(role_name)
                role_reps.append(role)
            
            # Assign roles to user
            self.keycloak_admin.assign_realm_roles(user_id, role_reps)
            
            logger.info(
                "keycloak_roles_assigned",
                user_id=user_id,
                roles=roles
            )
            
        except KeycloakError as e:
            logger.error(
                "keycloak_role_assignment_failed",
                user_id=user_id,
                roles=roles,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to assign roles to user"
            )
    
    async def get_user_roles(self, user_id: str) -> List[str]:
        """
        Get roles assigned to a user.
        
        Args:
            user_id: Keycloak user ID
            
        Returns:
            List of role names
        """
        try:
            roles = self.keycloak_admin.get_realm_roles_of_user(user_id)
            role_names = [role["name"] for role in roles]
            
            logger.info(
                "keycloak_user_roles_retrieved",
                user_id=user_id,
                roles=role_names
            )
            
            return role_names
            
        except KeycloakError as e:
            logger.error(
                "keycloak_user_roles_failed",
                user_id=user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve user roles"
            )
    
    async def enable_mfa(self, user_id: str) -> None:
        """
        Enable MFA for a user (TOTP).
        
        Args:
            user_id: Keycloak user ID
        """
        try:
            # Get required actions
            required_actions = self.keycloak_admin.get_required_actions_of_user(user_id)
            
            # Add TOTP if not already present
            if "VERIFY_EMAIL" not in required_actions:
                required_actions.append("CONFIGURE_TOTP")
            
            self.keycloak_admin.update_user(user_id, {
                "requiredActions": required_actions
            })
            
            logger.info("keycloak_mfa_enabled", user_id=user_id)
            
        except KeycloakError as e:
            logger.error(
                "keycloak_mfa_enable_failed",
                user_id=user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enable MFA for user"
            )
    
    async def disable_mfa(self, user_id: str) -> None:
        """
        Disable MFA for a user.
        
        Args:
            user_id: Keycloak user ID
        """
        try:
            # Remove TOTP from required actions
            required_actions = self.keycloak_admin.get_required_actions_of_user(user_id)
            required_actions = [a for a in required_actions if a != "CONFIGURE_TOTP"]
            
            self.keycloak_admin.update_user(user_id, {
                "requiredActions": required_actions
            })
            
            logger.info("keycloak_mfa_disabled", user_id=user_id)
            
        except KeycloakError as e:
            logger.error(
                "keycloak_mfa_disable_failed",
                user_id=user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to disable MFA for user"
            )
    
    async def get_users_by_organization(self, organization_id: str) -> List[Dict[str, Any]]:
        """
        Get all users belonging to an organization.
        
        Args:
            organization_id: Organization ID to filter by
            
        Returns:
            List of user dictionaries
        """
        try:
            # Get all users
            users = self.keycloak_admin.get_users({})
            
            # Filter by organization_id attribute
            org_users = [
                user for user in users
                if organization_id in user.get("attributes", {}).get("organization_id", [])
            ]
            
            logger.info(
                "keycloak_org_users_retrieved",
                organization_id=organization_id,
                count=len(org_users)
            )
            
            return org_users
            
        except KeycloakError as e:
            logger.error(
                "keycloak_org_users_failed",
                organization_id=organization_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve organization users"
            )
    
    async def sync_user_from_keycloak(self, keycloak_user_id: str) -> Dict[str, Any]:
        """
        Sync user from Keycloak to local database (SCIM-like).
        
        Args:
            keycloak_user_id: Keycloak user ID
            
        Returns:
            Synced user data
        """
        try:
            # Get user from Keycloak
            keycloak_user = self.keycloak_admin.get_user(keycloak_user_id)
            
            # Extract organization_id from attributes
            organization_id = keycloak_user.get("attributes", {}).get("organization_id", [None])[0]
            
            # Prepare user data for local database
            user_data = {
                "keycloak_id": keycloak_user_id,
                "username": keycloak_user["username"],
                "email": keycloak_user["email"],
                "first_name": keycloak_user["firstName"],
                "last_name": keycloak_user["lastName"],
                "enabled": keycloak_user["enabled"],
                "organization_id": organization_id,
                "email_verified": keycloak_user.get("emailVerified", False)
            }
            
            logger.info(
                "keycloak_user_synced",
                keycloak_user_id=keycloak_user_id,
                username=keycloak_user["username"]
            )
            
            return user_data
            
        except KeycloakError as e:
            logger.error(
                "keycloak_user_sync_failed",
                keycloak_user_id=keycloak_user_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to sync user from Keycloak"
            )


_keycloak_service: Optional["KeycloakService"] = None


def _is_keycloak_configured() -> bool:
    """True when SSO is enabled and the minimum OpenID settings are present."""
    if not settings.KEYCLOAK_ENABLED:
        return False
    if KeycloakOpenID is None:
        return False
    return bool(
        settings.KEYCLOAK_URL
        and settings.KEYCLOAK_REALM
        and settings.KEYCLOAK_CLIENT_ID
        and settings.KEYCLOAK_CLIENT_SECRET
    )


def get_keycloak_service() -> "KeycloakService":
    """Return a lazily constructed KeycloakService (never at import time)."""
    global _keycloak_service
    if not _is_keycloak_configured():
        raise RuntimeError("Keycloak is not enabled or not fully configured")
    if _keycloak_service is None:
        _keycloak_service = KeycloakService()
    return _keycloak_service

"""Authentication API Routes"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, Organization
from app.models.schemas import Token, UserLogin, UserCreate
from app.core.config import settings
from app.middleware.rate_limit import rate_limit

router = APIRouter()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


async def get_token_from_header(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract token from Authorization header without OAuth2 validation"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]  # Remove "Bearer " prefix
    return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user


async def get_current_active_user(
    token: str = Depends(oauth2_scheme),
    header_token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
) -> User:
    # DEV MODE: Bypass authentication for dev-token
    # Check both OAuth2 token and header token
    actual_token = token or header_token
    
    if actual_token == "dev-token":
        # Create or get dev user from database
        dev_org_id = "00000000-0000-0000-0000-000000000001"
        dev_user_id = "00000000-0000-0000-0000-000000000001"

        # Check if dev org exists, create if not
        org_result = await db.execute(
            select(Organization).where(Organization.id == dev_org_id)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            # Use random slug to avoid conflicts
            import uuid as uuid_lib
            org = Organization(
                id=dev_org_id,
                name="Dev Organization",
                slug=f"dev-{uuid_lib.uuid4().hex[:8]}"
            )
            db.add(org)
            await db.commit()

        # Check if dev user exists, create if not
        user_result = await db.execute(
            select(User).where(User.id == dev_user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            # Use a pre-h bcrypt password for "dev" to avoid runtime issues
            # bcrypt hash of "dev" is: $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYHqF5pXa9W
            user = User(
                id=dev_user_id,
                email="admin@omniusgrid.com",
                full_name="Dev Admin",
                role="admin",
                is_active=True,
                organization_id=dev_org_id,
                hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYHqF5pXa9W"
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return user

    # Normal authentication: local JWT first, then Keycloak SSO when enabled.
    if not actual_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user: Optional[User] = None

    try:
        current_user = await get_current_user(actual_token, db)
    except HTTPException:
        if settings.KEYCLOAK_ENABLED:
            from app.core.sso import authenticate_sso_token

            current_user = await authenticate_sso_token(actual_token, db)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@router.post("/login", response_model=Token, summary="Login with email and password", description="Authenticate user credentials and return a JWT access token. The token must be included in the Authorization header for subsequent requests.")
@rate_limit("10/minute")  # Stricter limit for login
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """Login and get access token"""
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", summary="Register a new user", description="Create a new user account. **WARNING**: This endpoint is for development only and should be disabled in production.")
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user (dev only - disable in production)"""
    # Check if user exists
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        organization_id=user_data.organization_id,
        role=user_data.role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return {"message": "User created successfully", "user_id": str(user.id)}


@router.get("/me", summary="Get current user information", description="Retrieve the authenticated user's profile information including email, name, role, and organization.")
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """Get current user information"""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "organization_id": str(current_user.organization_id) if current_user.organization_id else None,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None
    }


@router.get("/users", summary="Get organization users", description="Retrieve all users in the current user's organization. Used for task assignment and team management.")
async def get_organization_users(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all users in the organization for assignment"""
    if not current_user.organization_id:
        return {"items": [], "total": 0}
    
    result = await db.execute(
        select(User).where(User.organization_id == current_user.organization_id)
    )
    users = result.scalars().all()
    
    user_list = [
        {
            "id": str(user.id),
            "name": user.full_name,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "isActive": user.is_active,
            "createdAt": user.created_at.isoformat() if user.created_at else None,
            "updatedAt": user.updated_at.isoformat() if user.updated_at else None
        }
        for user in users
    ]
    
    return {
        "items": user_list,
        "total": len(user_list)
    }

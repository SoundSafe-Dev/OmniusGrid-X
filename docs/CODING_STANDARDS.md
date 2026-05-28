# OmniusGrid Coding Standards

## Overview

This document defines the coding standards for the OmniusGrid project to ensure consistency, readability, and maintainability across the codebase.

## General Principles

- **Readability**: Code should be easy to read and understand
- **Simplicity**: Prefer simple solutions over complex ones
- **Consistency**: Follow established patterns and conventions
- **Documentation**: Document complex logic and public APIs
- **Testing**: Write tests for all new code
- **Security**: Follow security best practices

## Python Standards (Backend)

### File Organization

```
backend/
├── app/
│   ├── api/              # API routes
│   ├── core/             # Core functionality (config, security)
│   ├── db/               # Database models and sessions
│   ├── middleware/       # Custom middleware
│   ├── models/           # Pydantic schemas
│   ├── services/         # Business logic
│   └── main.py           # Application entry point
├── tests/                # Test files
├── scripts/              # Utility scripts
└── requirements.txt      # Dependencies
```

### Naming Conventions

- **Modules**: `snake_case` (e.g., `oee_calculator.py`)
- **Classes**: `PascalCase` (e.g., `OEECalculator`)
- **Functions**: `snake_case` (e.g., `calculate_oee`)
- **Variables**: `snake_case` (e.g., `asset_id`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **Private members**: `_leading_underscore` (e.g., `_internal_method`)

### Type Hints

All functions must have type hints:

```python
from typing import Optional, List, Dict, Any
from datetime import datetime

def get_assets(
    organization_id: str,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Retrieve assets for an organization."""
    pass

async def create_asset(
    asset_data: AssetCreate,
    db: AsyncSession
) -> Asset:
    """Create a new asset."""
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def calculate_oee(
    availability: float,
    performance: float,
    quality: float
) -> float:
    """Calculate Overall Equipment Effectiveness.
    
    Args:
        availability: Availability percentage (0-1)
        performance: Performance percentage (0-1)
        quality: Quality percentage (0-1)
        
    Returns:
        OEE value (0-1)
        
    Raises:
        ValueError: If any parameter is outside 0-1 range
        
    Example:
        >>> calculate_oee(0.9, 0.85, 0.95)
        0.72675
    """
    if not 0 <= availability <= 1:
        raise ValueError("Availability must be between 0 and 1")
    return availability * performance * quality
```

### Error Handling

Use specific exceptions and provide context:

```python
from fastapi import HTTPException, status

async def get_asset(asset_id: str, db: AsyncSession) -> Asset:
    try:
        result = await db.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asset {asset_id} not found"
            )
        
        return asset
        
    except SQLAlchemyError as e:
        logger.error("database_error", asset_id=asset_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )
```

### Async/Await

Use async/await for I/O operations:

```python
# Good
async def get_telemetry(asset_id: str) -> List[Telemetry]:
    result = await db.execute(select(Telemetry).where(Telemetry.asset_id == asset_id))
    return result.scalars().all()

# Bad - blocking
def get_telemetry(asset_id: str) -> List[Telemetry]:
    result = db.execute(select(Telemetry).where(Telemetry.asset_id == asset_id))
    return result.scalars().all()
```

### Logging

Use structured logging with context:

```python
import structlog

logger = structlog.get_logger()

async def process_command(command: Command):
    logger.info(
        "command_processing_started",
        command_id=command.id,
        asset_id=command.asset_id,
        command_type=command.command_type
    )
    
    try:
        result = await execute_command(command)
        logger.info(
            "command_processing_completed",
            command_id=command.id,
            result=result
        )
    except Exception as e:
        logger.error(
            "command_processing_failed",
            command_id=command.id,
            error=str(e)
        )
        raise
```

### Database Queries

Use SQLAlchemy with async sessions:

```python
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

async def get_active_assets(
    organization_id: str,
    db: AsyncSession
) -> List[Asset]:
    """Get all active assets for an organization."""
    result = await db.execute(
        select(Asset)
        .where(
            and_(
                Asset.organization_id == organization_id,
                Asset.is_active == True
            )
        )
        .order_by(Asset.name)
    )
    return result.scalars().all()
```

### Configuration

Use environment variables with Pydantic Settings:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDPANDA_URL: str
    JWT_SECRET_KEY: str
    
    class Config:
        env_file = ".env"

settings = Settings()
```

## TypeScript Standards (Frontend)

### File Organization

```
frontend/src/
├── api/               # API client functions
├── components/        # Reusable components
│   ├── charts/       # Chart components
│   ├── nlp/          # NLP components
│   └── ui/           # UI components
├── hooks/            # Custom React hooks
├── pages/            # Page components
├── store/            # State management (Zustand)
└── utils/            # Utility functions
```

### Naming Conventions

- **Files**: `PascalCase.tsx` for components, `camelCase.ts` for utilities
- **Components**: `PascalCase` (e.g., `AssetCard`)
- **Functions**: `camelCase` (e.g., `getAssets`)
- **Variables**: `camelCase` (e.g., `assetId`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **Types/Interfaces**: `PascalCase` (e.g., `Asset`)

### Component Structure

```tsx
import { FC, useCallback, useState, useEffect } from 'react';

interface Props {
  assetId: string;
  onUpdate?: (assetId: string) => void;
}

export const AssetCard: FC<Props> = ({ assetId, onUpdate }) => {
  // State
  const [asset, setAsset] = useState<Asset | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Effects
  useEffect(() => {
    loadAsset();
  }, [assetId]);

  // Handlers
  const handleUpdate = useCallback(() => {
    onUpdate?.(assetId);
  }, [assetId, onUpdate]);

  // Render
  if (isLoading) return <Skeleton />;
  if (error) return <ErrorMessage message={error} />;
  if (!asset) return null;

  return (
    <div className="asset-card">
      <h3>{asset.name}</h3>
      <button onClick={handleUpdate}>Update</button>
    </div>
  );
};
```

### Type Definitions

Use interfaces for object shapes, types for unions:

```typescript
// Interface for object shapes
interface Asset {
  id: string;
  name: string;
  organizationId: string;
  currentPackMLState: string;
}

// Type for unions
type PackMLState = 'Idle' | 'Starting' | 'Execute' | 'Held' | 'Suspended';

// Type for function signatures
type AssetHandler = (asset: Asset) => void;
```

### Custom Hooks

Create reusable custom hooks:

```typescript
import { useState, useEffect, useCallback } from 'react';

export function useAsset(assetId: string) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAsset = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAsset(assetId);
      setAsset(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [assetId]);

  useEffect(() => {
    loadAsset();
  }, [loadAsset]);

  return { asset, isLoading, error, refetch: loadAsset };
}
```

### API Calls

Use axios with proper error handling:

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export async function getAsset(assetId: string): Promise<Asset> {
  try {
    const response = await api.get<Asset>(`/assets/${assetId}`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      throw new Error(error.response?.data?.detail || 'Failed to fetch asset');
    }
    throw error;
  }
}
```

### State Management

Use Zustand for global state:

```typescript
import { create } from 'zustand';

interface AssetStore {
  assets: Asset[];
  selectedAsset: Asset | null;
  setAssets: (assets: Asset[]) => void;
  selectAsset: (asset: Asset) => void;
}

export const useAssetStore = create<AssetStore>((set) => ({
  assets: [],
  selectedAsset: null,
  setAssets: (assets) => set({ assets }),
  selectAsset: (asset) => set({ selectedAsset: asset }),
}));
```

### Performance

Use React.memo, useCallback, useMemo:

```tsx
import { memo, useCallback, useMemo } from 'react';

export const AssetList = memo(({ assets }: { assets: Asset[] }) => {
  const sortedAssets = useMemo(
    () => assets.sort((a, b) => a.name.localeCompare(b.name)),
    [assets]
  );

  const handleSelect = useCallback((assetId: string) => {
    console.log('Selected:', assetId);
  }, []);

  return (
    <div>
      {sortedAssets.map((asset) => (
        <AssetCard
          key={asset.id}
          asset={asset}
          onSelect={handleSelect}
        />
      ))}
    </div>
  );
});
```

## SQL Standards (Database)

### Naming Conventions

- **Tables**: `snake_case` (e.g., `packml_states`)
- **Columns**: `snake_case` (e.g., `state_entered_at`)
- **Indexes**: `idx_table_column` (e.g., `idx_telemetry_time`)
- **Constraints**: `ck_table_condition` (e.g., `ck_assets_is_active`)
- **Foreign Keys**: `fk_table_column` (e.g., `fk_assets_organization_id`)

### Query Style

```sql
-- Use uppercase for keywords
SELECT 
    a.id,
    a.name,
    a.current_packml_state,
    COUNT(t.id) AS telemetry_count
FROM assets a
LEFT JOIN telemetry t ON a.id = t.asset_id
WHERE a.organization_id = 'org-001'
    AND a.is_active = TRUE
GROUP BY a.id, a.name, a.current_packml_state
ORDER BY a.name;
```

### Indexing

Create appropriate indexes for frequently queried columns:

```sql
-- Single column index
CREATE INDEX idx_telemetry_time ON telemetry(time DESC);

-- Composite index
CREATE INDEX idx_telemetry_asset_time ON telemetry(asset_id, time DESC);

-- Partial index
CREATE INDEX idx_active_assets ON assets(id) WHERE is_active = TRUE;
```

### Comments

Add comments for complex queries:

```sql
-- Calculate OEE for all assets in the last 24 hours
WITH time_in_execute AS (
    SELECT 
        asset_id,
        SUM(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS total_seconds
    FROM packml_states
    WHERE state = 'Execute'
        AND state_entered_at > NOW() - INTERVAL '24 hours'
    GROUP BY asset_id
),
total_time AS (
    SELECT 
        asset_id,
        SUM(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS total_seconds
    FROM packml_states
    WHERE state_entered_at > NOW() - INTERVAL '24 hours'
    GROUP BY asset_id
)
SELECT 
    a.id,
    a.name,
    COALESCE(te.total_seconds, 0) / NULLIF(tt.total_seconds, 0) AS availability
FROM assets a
LEFT JOIN time_in_execute te ON a.id = te.asset_id
LEFT JOIN total_time tt ON a.id = tt.asset_id;
```

## Git Standards

### Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `hotfix/` - Critical production fixes
- `refactor/` - Code refactoring
- `docs/` - Documentation changes
- `test/` - Test changes

Examples:
```
feature/http-rest-collector
fix/memory-leak-websocket
hotfix/security-vulnerability
refactor/oee-calculation
docs/api-authentication
test-integration-commands
```

### Commit Messages

Follow conventional commits:

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Code style (formatting)
- `refactor`: Code refactoring
- `test`: Test changes
- `chore`: Maintenance

Examples:
```
feat(collectors): add HTTP/REST collector for API data collection

Implement new collector for polling REST APIs at configurable intervals.
Supports authentication, pagination, and error handling.

Closes #123

fix(websocket): resolve memory leak in connection handler

The WebSocket connection handler was not properly cleaning up
event listeners on disconnect, causing memory to accumulate
over time.

Fixes #456
```

## Security Standards

### Input Validation

Validate all inputs:

```python
from pydantic import BaseModel, validator

class AssetCreate(BaseModel):
    name: str
    asset_type_id: str
    organization_id: str
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()
```

### SQL Injection Prevention

Use parameterized queries:

```python
# Good - parameterized
await db.execute(
    select(Asset).where(Asset.id == asset_id)
)

# Bad - string interpolation (SQL injection risk)
await db.execute(
    f"SELECT * FROM assets WHERE id = '{asset_id}'"
)
```

### Secret Management

Never hardcode secrets:

```python
# Good - environment variable
import os
SECRET_KEY = os.getenv('JWT_SECRET_KEY')

# Bad - hardcoded
SECRET_KEY = 'dev_secret_key_change_in_production'
```

### Authentication

Always validate authentication:

```python
from fastapi import Depends, HTTPException, status
from app.core.security import get_current_user

@router.get("/assets")
async def get_assets(
    current_user: User = Depends(get_current_user)
):
    # User is authenticated
    pass
```

## Testing Standards

### Test Organization

```
tests/
├── unit/              # Unit tests
├── integration/       # Integration tests
├── e2e/              # End-to-end tests
└── fixtures/         # Test fixtures
```

### Test Naming

Use descriptive names:

```python
def test_get_asset_returns_asset_when_exists():
    pass

def test_get_asset_returns_none_when_not_found():
    pass

def test_get_asset_raises_error_when_database_fails():
    pass
```

### Test Structure

Arrange-Act-Assert pattern:

```python
def test_create_asset():
    # Arrange
    asset_data = AssetCreate(
        name="Test Asset",
        asset_type_id="type-001",
        organization_id="org-001"
    )
    
    # Act
    result = await create_asset(asset_data, db)
    
    # Assert
    assert result.name == "Test Asset"
    assert result.id is not None
```

## Documentation Standards

### Code Comments

Comment why, not what:

```python
# Good - explains why
# We use exponential backoff to avoid overwhelming the database
# during connection issues
retry_delay = min(initial_delay * (2 ** attempt), max_delay)

# Bad - obvious
# Increment retry delay
retry_delay = retry_delay * 2
```

### README Sections

Include these sections in README:
- Overview
- Features
- Installation
- Usage
- Configuration
- API Documentation
- Contributing
- License

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Coding Standards

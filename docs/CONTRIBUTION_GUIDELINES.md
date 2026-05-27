# OmniusGrid Contribution Guidelines

## Overview

Thank you for your interest in contributing to OmniusGrid! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### Fork and Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/your-username/OmniusGrid.git
cd OmniusGrid

# Add upstream remote
git remote add upstream https://github.com/original-org/OmniusGrid.git
```

### Create a Branch

```bash
# Create a new branch for your feature
git checkout -b feature/your-feature-name

# Or for a bug fix
git checkout -b fix/your-bug-fix
```

## Development Workflow

### 1. Make Changes

- Follow the coding standards (see CODING_STANDARDS.md)
- Write tests for your changes
- Update documentation as needed

### 2. Test Your Changes

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test

# Linting
cd backend
black app
isort app
flake8 app

cd frontend
npm run lint
npx tsc --noEmit
```

### 3. Commit Your Changes

```bash
# Stage changes
git add .

# Commit with conventional commit message
git commit -m "feat: add new feature for asset monitoring"
```

### Commit Message Format

We use conventional commits:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, etc.)
- `refactor:` Code refactoring
- `test:` Test changes
- `chore:` Maintenance tasks

Examples:
```
feat: add HTTP/REST collector for API data collection
fix: resolve memory leak in WebSocket connection handler
docs: update API documentation for authentication endpoints
refactor: simplify OEE calculation logic
test: add integration tests for command executor
```

### 4. Sync with Upstream

```bash
# Fetch upstream changes
git fetch upstream

# Rebase your branch on upstream/main
git rebase upstream/main

# Resolve any conflicts
# ...

# Push to your fork
git push origin feature/your-feature-name
```

## Pull Request Process

### 1. Create Pull Request

- Go to GitHub and create a pull request from your branch
- Use the PR template (provided below)
- Link to any related issues

### 2. PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Related Issues
Fixes #123
Related to #456

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed
- [ ] Screenshots for UI changes (if applicable)

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] Tests added/updated
- [ ] All tests passing
```

### 3. Code Review

- Address reviewer feedback
- Make requested changes
- Keep PR focused and small
- Respond to comments in a timely manner

### 4. Merge

- After approval, maintainers will merge
- Squash commits for clean history
- Delete branch after merge

## Coding Standards

### Python (Backend)

- Use type hints for all functions
- Follow PEP 8 style guide
- Use docstrings for all modules, classes, and functions
- Keep functions under 50 lines
- Use async/await for I/O operations
- Handle exceptions appropriately

Example:
```python
from typing import Optional
from fastapi import HTTPException, status

async def get_asset(asset_id: str, db: AsyncSession) -> Optional[Asset]:
    """
    Retrieve an asset by ID.
    
    Args:
        asset_id: The unique identifier of the asset
        db: Database session
        
    Returns:
        Asset object if found, None otherwise
        
    Raises:
        HTTPException: If database error occurs
    """
    try:
        result = await db.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
```

### TypeScript (Frontend)

- Use functional components with hooks
- Use TypeScript for all new code
- Follow React best practices
- Use proper prop types
- Handle loading and error states
- Use useCallback/useMemo for performance

Example:
```tsx
import { FC, useCallback, useState } from 'react';

interface AssetCardProps {
  assetId: string;
  assetName: string;
  onUpdate: (assetId: string) => void;
}

export const AssetCard: FC<AssetCardProps> = ({
  assetId,
  assetName,
  onUpdate
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpdate = useCallback(() => {
    setIsLoading(true);
    setError(null);
    onUpdate(assetId)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [assetId, onUpdate]);

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;

  return (
    <div>
      <h3>{assetName}</h3>
      <button onClick={handleUpdate}>Update</button>
    </div>
  );
};
```

### SQL (Database)

- Use uppercase for SQL keywords
- Use snake_case for table/column names
- Add comments for complex queries
- Use parameterized queries
- Index frequently queried columns

Example:
```sql
-- Get assets with recent telemetry
SELECT 
    a.id,
    a.name,
    a.current_packml_state,
    t.metric_name,
    t.value,
    t.unit
FROM assets a
LEFT JOIN LATERAL (
    SELECT metric_name, value, unit
    FROM telemetry
    WHERE asset_id = a.id
    ORDER BY time DESC
    LIMIT 1
) t ON true
WHERE a.is_active = true
ORDER BY a.name;
```

## Testing Guidelines

### Unit Tests

- Test individual functions and components
- Mock external dependencies
- Test edge cases and error conditions
- Aim for >80% code coverage

Example:
```python
import pytest
from app.services.oee_calculator import OEECalculator

def test_oee_calculation():
    calculator = OEECalculator()
    
    # Test normal case
    result = calculator.calculate(
        availability=0.9,
        performance=0.85,
        quality=0.95
    )
    assert result == pytest.approx(0.72675)
    
    # Test edge case - zero availability
    result = calculator.calculate(
        availability=0.0,
        performance=0.85,
        quality=0.95
    )
    assert result == 0.0
```

### Integration Tests

- Test API endpoints
- Test database operations
- Test message broker operations
- Use test database

Example:
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_asset():
    response = client.post(
        "/api/v1/assets",
        json={
            "name": "Test Asset",
            "asset_type_id": "type-001",
            "organization_id": "org-001"
        },
        headers={"Authorization": "Bearer dev-token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Asset"
    assert "id" in data
```

### E2E Tests

- Test user workflows
- Test critical paths
- Use Playwright for frontend
- Test across browsers

Example:
```typescript
import { test, expect } from '@playwright/test';

test('user can login and view dashboard', async ({ page }) => {
  await page.goto('http://localhost:3000/login');
  
  await page.fill('input[name="username"]', 'dev');
  await page.fill('input[name="password"]', 'dev');
  await page.click('button[type="submit"]');
  
  await expect(page).toHaveURL('http://localhost:3000/');
  await expect(page.locator('h1')).toContainText('Dashboard');
});
```

## Documentation Guidelines

### Code Documentation

- Add docstrings to all functions
- Document parameters and return values
- Add inline comments for complex logic
- Keep documentation up to date

### API Documentation

- Update OpenAPI spec for new endpoints
- Add examples for request/response
- Document error codes
- Add authentication requirements

### User Documentation

- Update README for user-facing changes
- Add screenshots for UI changes
- Update glossary for new terms
- Add troubleshooting guides

## Review Guidelines

### For Reviewers

- Be constructive and specific
- Explain the "why" behind suggestions
- Focus on the code, not the person
- Acknowledge good work
- Respond in a timely manner

### For Contributors

- Be open to feedback
- Ask questions if unclear
- Explain your reasoning
- Learn from reviews
- Thank reviewers

## Issue Reporting

### Bug Reports

Use the bug report template:

```markdown
## Description
Clear description of the bug

## Steps to Reproduce
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Screenshots
If applicable, add screenshots

## Environment
- OS: [e.g. macOS, Linux]
- Browser: [e.g. Chrome, Firefox]
- Version: [e.g. 1.0.0]

## Additional Context
Add any other context about the problem
```

### Feature Requests

Use the feature request template:

```markdown
## Problem Description
Clear description of the problem

## Proposed Solution
Description of the proposed solution

## Alternatives Considered
Description of alternative approaches

## Additional Context
Add any other context or screenshots
```

## Release Process

### Versioning

We follow semantic versioning:
- MAJOR: Breaking changes
- MINOR: New features (backwards compatible)
- PATCH: Bug fixes (backwards compatible)

### Release Checklist

- [ ] All tests passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Version bumped
- [ ] Release notes written
- [ ] Tagged in Git
- [ ] Published to registry

## Getting Help

- **GitHub Issues**: For bugs and feature requests
- **Discord**: For questions and discussions
- **Documentation**: Check existing docs first
- **Stack Overflow**: Use `omniusgrid` tag

## Recognition

Contributors will be recognized in:
- CONTRIBUTORS.md file
- Release notes
- Project website

## License

By contributing, you agree that your contributions will be licensed under the project's license.

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Contribution Guidelines

#!/bin/bash
# Export OmniusGrid API Documentation to HTML and PDF

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCS_DIR="$PROJECT_ROOT/docs"
OPENAPI_JSON="$DOCS_DIR/openapi.json"
HTML_OUTPUT="$DOCS_DIR/api-documentation.html"
PDF_OUTPUT="$DOCS_DIR/api-documentation.pdf"

echo "Exporting OmniusGrid API Documentation..."

# Check if backend is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "Error: Backend API is not running. Please start the backend first."
    echo "Run: cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
    exit 1
fi

# Download OpenAPI JSON schema
echo "Downloading OpenAPI schema from http://localhost:8000/openapi.json..."
curl -s http://localhost:8000/openapi.json -o "$OPENAPI_JSON"

if [ ! -f "$OPENAPI_JSON" ]; then
    echo "Error: Failed to download OpenAPI schema"
    exit 1
fi

# Check if redoc-cli is installed
if ! command -v redoc-cli &> /dev/null; then
    echo "Installing redoc-cli..."
    npm install -g @redocly/cli
fi

# Generate HTML using Redoc
echo "Generating HTML documentation..."
redoc-cli bundle "$OPENAPI_JSON" -o "$HTML_OUTPUT"

if [ ! -f "$HTML_OUTPUT" ]; then
    echo "Error: Failed to generate HTML documentation"
    exit 1
fi

# Check if weasyprint is installed for PDF generation
if command -v weasyprint &> /dev/null; then
    echo "Generating PDF documentation..."
    weasyprint "$HTML_OUTPUT" -o "$PDF_OUTPUT"
    echo "PDF documentation generated: $PDF_OUTPUT"
else
    echo "Warning: weasyprint not found. Skipping PDF generation."
    echo "To install: pip install weasyprint"
fi

echo "HTML documentation generated: $HTML_OUTPUT"
echo "OpenAPI schema saved: $OPENAPI_JSON"
echo ""
echo "Documentation export complete!"

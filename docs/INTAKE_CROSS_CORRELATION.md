# Intake Cross-Correlation Feature

## Overview

The OmniusGrid intake system now supports comprehensive cross-correlation across multiple document types, including multi-page PDFs, DOCX documents, images, and multi-tab spreadsheets. This feature enables linking data across files by shared keys (e.g., asset IDs, order numbers, dates) and running correlation AI analysis across domains.

## Supported Document Types

- **Spreadsheets**: Multi-tab Excel files (`.xlsx`, `.xls`) with per-tab profiling
- **PDFs**: Multi-page PDF documents with structure extraction (headers, tables, text blocks)
- **DOCX**: Word documents with heading hierarchy and table extraction
- **Images**: PNG, JPEG, etc. with text extraction via vision model

## Architecture

### Phase 1: Document Structure Extraction

- `pdf_parser.py`: Extracts pages, headers, tables, text blocks, and metadata from PDFs
- `docx_parser.py`: Extracts heading hierarchy, sections, tables, and metadata from DOCX
- `image_text_extractor.py`: Extracts text from images using Google Gemini multimodal vision

### Phase 2: Domain Mapping

- `document_domain_mapper.py`: Maps document sections to `DomainType` (PROD, LOG, MNT, QUA, SAF, etc.)
- `image_domain_mapper.py`: Maps image text and metadata to domains

### Phase 3: Scenario Building

- `document_scenario_builder.py`: Converts document structures into `CorrelationScenario` objects
- `image_scenario_builder.py`: Converts image extractions into scenarios
- Modes: section, document, table, image, batch

### Phase 4: Cross-File Correlation

- `shared_key_detector.py`: Extracts and normalizes shared keys from text, filenames, metadata
- `cross_file_scenario_builder.py`: Builds scenarios linking multiple intake items by shared keys

### Phase 5: API Endpoints

- `POST /api/nlp/intake/upload`: Upload and parse files with structure-aware processing
- `POST /api/nlp/intake/{item_id}/analyze`: Analyze intake items by data type
- `POST /api/nlp/intake/cross-correlate`: Correlate arbitrary intake items by shared keys
- `POST /api/analysis-sessions/{session_id}/upload`: Upload to session with new parsing
- `POST /api/analysis-sessions/{session_id}/correlate`: Correlate all session data sources

## API Usage

### Upload to Intake

```bash
POST /api/nlp/intake/upload
Content-Type: multipart/form-data

file: <binary>
data_type: "pdf" | "docx" | "image" | "spreadsheet"
```

Response includes:
- `processing_time_estimate_seconds`: Estimated time to process
- `structure_counts`: {pages, sections, tables, images} counts
- `shared_keys`: Auto-detected shared keys
- `structure_metadata`: Document structure info

### Analyze Intake Item

```bash
POST /api/nlp/intake/{item_id}/analyze
Content-Type: application/json

{
  "mode": "section" | "document" | "table" | "image" | "batch",
  "shared_keys": ["optional", "manual", "keys"],
  "auto_integrate": true
}
```

### Cross-File Correlate Intake Items

```bash
POST /api/nlp/intake/cross-correlate
Content-Type: application/json

{
  "item_ids": ["uuid1", "uuid2", "uuid3"],
  "shared_keys": ["optional", "manual", "keys"],
  "auto_integrate": true
}
```

### Session Correlation

```bash
POST /api/analysis-sessions/{session_id}/correlate
Content-Type: application/json

{
  "shared_keys": ["optional", "manual", "keys"],
  "auto_integrate": true
}
```

## Shared Keys

Shared keys are extracted from:
- Filenames (e.g., `PO-123-report.pdf` → `PO-123`)
- Document metadata (title, author, subject)
- Content text (asset IDs, order numbers, dates)
- Structured records (table columns, spreadsheet rows)

Normalization rules:
- Convert to uppercase
- Replace underscores/hyphens with hyphens
- Trim whitespace
- Remove leading/trailing special characters

## Domain Mapping

### Document Domains

- **PROD**: Production (production, output, manufacturing, line, shift)
- **LOG**: Logistics (logistics, delivery, shipment, transport, freight)
- **MNT**: Maintenance (maintenance, repair, asset, failure, downtime)
- **QUA**: Quality (quality, inspection, defect, compliance, audit)
- **SAF**: Safety (safety, incident, hazard, injury, ppe)
- **FIN**: Finance (cost, budget, revenue, expense, invoice)
- **HR**: HR (employee, staffing, training, hiring, leave)
- **OPS**: Operations (operations, schedule, shift, roster)

### Image Domains

Image-specific keywords plus general document keywords.

## Configuration

Add to `backend/app/core/config.py`:

```python
# Vision Model Configuration
VISION_MODEL_ENABLED = os.getenv("VISION_MODEL_ENABLED", "false").lower() == "true"
VISION_MODEL_PROVIDER = os.getenv("VISION_MODEL_PROVIDER", "gemini")
VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME", "gemini-1.5-pro")
VISION_MAX_IMAGE_BYTES = int(os.getenv("VISION_MAX_IMAGE_BYTES", "10485760"))  # 10MB
```

Set environment variables:
- `VISION_MODEL_ENABLED=true` to enable image text extraction
- `GOOGLE_API_KEY` for Gemini vision model

## Database Migration

Run migration `021_intake_cross_correlation.sql` to add:
- `shared_keys` JSON column to `intake_items` and `session_data_sources`
- `structure_metadata` JSON column for document structure info
- `processing_time_seconds` INTEGER for actual processing time
- GIN indexes on `shared_keys` for fast lookups

## Testing

Unit tests are provided in `backend/tests/`:
- `test_shared_key_detector.py`
- `test_document_domain_mapper.py`
- `test_image_domain_mapper.py`
- `test_document_scenario_builder.py`
- `test_image_scenario_builder.py`
- `test_cross_file_scenario_builder.py`

Run with:
```bash
cd backend
python3 -m pytest tests/test_*.py -v
```

## Processing Time Estimates

Estimates are provided based on document type and size:
- PDF: ~0.5s per page
- DOCX: ~0.3s per section
- Image: ~2s per image (vision model)
- Spreadsheet: ~0.1s per 1000 rows

## Scenario Caps

For large documents, scenario caps limit the number of scenarios generated:
- Section mode: Max 50 scenarios (sections)
- Table mode: Max 20 scenarios (tables)
- Image mode: Max 30 scenarios (images)
- Batch mode: 1 scenario (aggregated)

## Future Enhancements

- Gemma4 model integration for vision
- Additional document formats (RTF, ODT)
- OCR for scanned PDFs
- Advanced shared key detection with ML
- Cross-session correlation

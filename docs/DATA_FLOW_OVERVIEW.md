# OmniusGrid Data Flow Overview

## Purpose

This document explains how an uploaded file moves through the OmniusGrid pipeline.

## Pipeline

```text
Upload
  ↓
Intake
  ↓
Parse
  ↓
Detect domains and shared keys
  ↓
Build correlation scenarios
  ↓
Run correlation
  ↓
Analysis session
```

## 1. Upload

The user uploads a supported file through the intake API.

Examples include CSV, Excel, PDF, DOCX, and image files.

## 2. Intake

The uploaded file becomes an intake item. The system stores information such as:

- File name
- File type
- User ownership
- Processed data
- Metadata

## 3. Parse

The appropriate parser reads the uploaded file and converts it into structured information.

Depending on the file type, this may include:

- Spreadsheet rows
- Tables
- Document text
- Metadata

## 4. Detect Domains and Shared Keys

The system identifies operational domains represented in the uploaded data, such as:

- Production
- Maintenance
- Quality
- Logistics

It also extracts shared keys, including:

- Asset IDs
- Serial numbers
- Work orders
- Purchase orders
- Dates

These shared keys allow related information from different files to be connected.

## 5. Build Correlation Scenarios

Files that share common keys are grouped into correlation scenarios.

Each scenario can contain:

- Active domains
- Operational metrics
- Shared interaction keys
- Cross-domain links

## 6. Run Correlation

The correlation engine analyzes each scenario to detect relationships, risks, and cross-domain connections between the uploaded datasets.

## 7. Analysis Session

The correlation results are collected into an analysis session where users can review:

- Findings
- Risk scores
- Detected relationships
- Involved domains
- Source files

## Summary

Overall flow:

```text
User Upload
    ↓
Intake
    ↓
Parse
    ↓
Detect Domains & Shared Keys
    ↓
Build Correlation Scenarios
    ↓
Run Correlation
    ↓
Analysis Session
```
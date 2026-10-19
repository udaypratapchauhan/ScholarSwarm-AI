# ScholarSwarm AI

**Evidence-First Multi-Agent Scholarship Research & Verification Platform**  
*Built for the TetraNoodle AI Hackathon 2026*

ScholarSwarm AI automates university scholarship discovery, qualification verification, explainable ranking, and statement-of-purpose generation through a network of collaborating autonomous AI agents.

---

## 1. Project Directory Structure

```text
AI Project Swarm/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application & health diagnostics
│   │   ├── database.py          # SQLite schema init, queries & foreign keys
│   │   ├── schemas.py           # Pydantic models, strict enums & validators
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── ssrf.py          # SSRF defense, DNS pre-resolution & connection pinning
│   ├── agents/
│   │   └── __init__.py          # Agent implementations (Scheduled for Milestones 1B–3)
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_schemas.py      # Schema validation & type constraints tests
│   │   ├── test_ssrf.py         # Deterministic offline SSRF & redirect tests
│   │   ├── test_database.py     # SQLite init, persistence & foreign key tests
│   │   └── test_health.py       # Healthy (200) and unhealthy (503) status tests
│   └── requirements.txt         # Backend Python dependencies
├── config/
│   └── scoring_weights.json     # External configurable scoring weights for MRA
├── frontend/
│   └── README.md                # React/Vite UI placeholder (Milestone 4)
├── .env.example                 # Safe environment configuration template
├── .gitignore                   # Excludes credentials, *.db, uploads, and caches
└── README.md                    # Project documentation
```

---

## 2. Implemented Scope (Milestone 1A)

Milestone 1A provides the foundational architecture and security core:

- **Canonical Pydantic Schemas (`backend/app/schemas.py`):**
  - Typed models for `StudentProfile`, `OpportunityStub`, `VerifiedOpportunity`, `RankedOpportunity`, `SOPDraft`, and `PipelineEvent`.
  - Strict enums: `VerificationTier` (`T1`, `T2`, `T3`, `T4`), `EligibilityStatus` (`eligible`, `ineligible`, `unknown`), and `CycleStatus` (`current`, `expired`, `uncertain`).
  - Independent tracking of program admission eligibility vs. scholarship funding eligibility.
  - Cross-field validation enforcing grading scale (`cgpa_scale`) whenever CGPA is provided.
  - Prohibits arbitrary linear normalization across grading systems without official conversion data.
  - Enforces official source URLs and verbatim evidence excerpts.
- **SSRF Defense with Connection Pinning (`backend/app/utils/ssrf.py`):**
  - Allows only HTTP and HTTPS schemes; strictly rejects credentials embedded in URLs.
  - Pre-resolves DNS and validates all returned IPv4 and IPv6 addresses against loopback, private RFC 1918, link-local, cloud metadata (`169.254.169.254`), multicast, and reserved spaces.
  - Rebind / TOCTOU protection: pins the TCP connection to the pre-validated IP address while preserving the original hostname for HTTP `Host` and TLS SNI certificate validation.
  - Disables automatic redirects, manually re-validating the resolved destination at each hop up to a maximum of 3 redirects.
- **SQLite Persistence & Declarative Schemas (`backend/app/database.py`):**
  - Declarative schema initialization for `sessions`, `opportunities`, `sop_drafts`, `pipeline_events`, and `pipeline_errors`.
  - SQLite foreign key constraint enforcement enabled via `PRAGMA foreign_keys = ON;`.
  - JSON serialization for structured lists and key-value metrics.
- **FastAPI Core & Health Check (`backend/app/main.py`):**
  - Application startup lifespan event ensuring declarative table creation.
  - Resilient health endpoint `GET /api/health` returning `200 OK` when SQLite connectivity succeeds, and `503 Service Unavailable` when database operations fail.
- **Deterministic Test Suite:**
  - 66 comprehensive tests passing across schemas, SSRF scenarios, SQLite operations, and health diagnostics without internet access or API token consumption.

---

## 3. Prerequisites & Environment Setup

### Prerequisites
- Python 3.11 or Python 3.12 installed.
- Git (configured locally).

### Setup Instructions

1. **Clone or navigate to the workspace directory:**
   ```bash
   cd "AI Project Swarm"
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r backend/requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   copy .env.example .env
   # Or on Linux/macOS:
   cp .env.example .env
   ```
   *Note: Never commit `.env` to version control. The `.gitignore` file strictly blocks `.env`.*

---

## 4. Running the Backend Server

Start the FastAPI application with Uvicorn:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Once running:
- **API Health Check:** `http://127.0.0.1:8000/api/health`
- **Interactive OpenAPI Documentation:** `http://127.0.0.1:8000/docs`

---

## 5. Running the Test Suite

Execute the automated test suite using `pytest`:

```bash
python -m pytest backend/tests -v
```

All 66 tests run offline using mocks and temporary databases. No live API tokens or search credits are consumed.

---

## 6. Known Limitations & Deferred Scope

Per project planning constraints, the following features are scheduled for subsequent milestones:

| Feature / Component | Status / Milestone | Description |
| :--- | :--- | :--- |
| **Student Profile Agent (SPA)** | Milestone 1B | PDF/DOCX file parsing and public GitHub profile extraction |
| **Opportunity Research Agent (ORA)** | Milestone 2 | Tavily/Serper search query execution and deduplication |
| **Eligibility & Verification Agent (EEVA)** | Milestone 2 | Content extraction via Trafilatura and deterministic eligibility classification |
| **Matching & Ranking Agent (MRA)** | Milestone 3 | Python scoring function and separate admission/scholarship sections |
| **Application / SOP Assistant (ASA)** | Milestone 3 | Grounded Statement of Purpose generation |
| **React Frontend** | Milestone 4 | Vite + React + Tailwind dashboard with 3s polling |
| **WebSockets** | Deferred | Optional upgrade from HTTP polling |
| **OCR (Tesseract)** | Deferred | Fallback for scanned PDF transcripts if text extraction fails |
| **Docker Compose** | Deferred | Containerization for final judging package |

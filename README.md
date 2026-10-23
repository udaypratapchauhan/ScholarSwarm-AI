# ScholarSwarm AI

**Evidence-First Multi-Agent Scholarship Research & Verification Platform**  
*Built for the TetraNoodle AI Hackathon 2026*

ScholarSwarm AI automates university scholarship discovery, qualification verification, explainable multi-factor ranking, and statement-of-purpose generation through a network of five collaborating autonomous agents. It eliminates scholarship search hallucination by strictly separating live search discovery from official-source evidence verification.

---

## 1. Problem Statement & Solution

### The Problem
Finding and applying for international university scholarships is broken:
- **Information Overload & Fraudulent Aggregators:** Search results are saturated with commercial aggregators, expired schemes, and unverified blog posts.
- **Hallucinated Requirements:** Generic AI tools frequently invent eligibility criteria, deadlines, and funding figures.
- **Conflated Admissions vs. Funding Requirements:** Students waste application fees applying for scholarships when they meet program admissions criteria but miss strict funding eligibility (e.g., nationality exclusions or minimum GPA thresholds).
- **Incompatible Grading Scales:** Arbitrary linear normalization across disparate international grading scales (e.g., 4.0, 10.0, or percentages) produces false eligibility claims.

### The Solution: ScholarSwarm AI
ScholarSwarm AI deploys five specialized autonomous agents working in orchestrated succession. Every claim, deadline, and eligibility determination is tied directly to verifiable web provenance, enforcing a strict hierarchy of evidence tiers (T1 to T4) before an opportunity can ever qualify as a verified recommendation.

---

## 2. Five-Agent Architecture & Workflow

```
[Student Profile / Resume / Transcript]
                  │
                  ▼
   ┌───────────────────────────────┐
   │ SPA — Student Profile Agent   │  Extracts GPA, scale, degrees, tests, & skills
   └──────────────┬────────────────┘
                  │
                  ▼
   ┌───────────────────────────────┐
   │ ORA — Opportunity Research    │  Formulates queries; queries Tavily Search API
   └──────────────┬────────────────┘  (Live search with offline mock fallback)
                  │
                  ▼
   ┌───────────────────────────────┐
   │ EEVA — Eligibility & Evidence │  SSRF-safe fetch; domain trust classification;
   │        Verification Agent     │  evaluates admission vs. scholarship rules
   └──────────────┬────────────────┘
                  │
                  ▼
   ┌───────────────────────────────┐
   │ MRA — Matchmaking & Ranking   │  Scores candidates via configurable weights;
   │       Agent                   │  strictly requires T4 official proof for Top-5
   └──────────────┬────────────────┘
                  │
                  ▼
   ┌───────────────────────────────┐
   │ ASA — Application Strategy    │  Generates grounded SOP outline & strategy
   │       Agent                   │  cited directly from verified source excerpts
   └───────────────────────────────┘
```

1. **SPA — Student Profile Agent (`backend/agents/spa.py`):**
   - Ingests PDF and DOCX resumes, transcripts, or direct profile forms.
   - Extracts candidate name, email, nationality, degree level, CGPA, grading scale, standardized test scores (IELTS/TOEFL/GRE), and work experience.
   - Differentiates explicit skills from inferred competencies.
   - Emits structured events to SQLite and enforces validation schemas.

2. **ORA — Opportunity Research Agent (`backend/agents/ora.py`):**
   - Synthesizes student profile attributes into targeted search queries.
   - Discovers candidate opportunities via the live **Tavily AI Search API**.
   - Normalizes and deduplicates URLs, stripping tracking parameters and fragments.
   - Enforces regional and country relevancy using a centralized country configuration catalog.
   - Seamlessly falls back to an offline curated mock pool if no search API key is provided.

3. **EEVA — Eligibility & Evidence Verification Agent (`backend/agents/eeva.py`):**
   - Inspects candidate URLs through an SSRF-safe HTTP client with DNS pre-resolution, connection pinning, and redirect verification.
   - Classifies domain trust: `official_provider` (e.g., `.edu`, `.ac.uk`, `.gov`, `.gc.ca`), `reliable_secondary` (DAAD, Campus France, Fulbright), `aggregator`, or `unknown`.
   - Independently assesses **admission eligibility** versus **scholarship funding eligibility**.
   - Assigns rigorous evidence tiers:
     - **T4:** Official provider domain + successful HTTP 200 fetch + verbatim grounded evidence excerpt.
     - **T3:** Reliable secondary authority or official domain without grounded excerpt.
     - **T2:** Accessible non-official web sources / informational portals.
     - **T1:** Unverified, inaccessible, or mock demonstration fallback.
   - Partitions opportunities into mutually exclusive result groups: `confirmed_eligible`, `potentially_eligible`, `ineligible`, or `expired`.

4. **MRA — Matchmaking & Ranking Agent (`backend/agents/mra.py`):**
   - Evaluates multi-factor alignment: Field Alignment (30%), Funding Coverage (25%), Deadline Proximity (20%), Eligibility Clarity (15%), and Data Completeness (10%).
   - Weights are externalized and dynamically configurable via `config/scoring_weights.json`.
   - **Strict Verification Gate:** Only opportunities achieving **T4 verification from official providers** qualify for Top-5 recommendations. Lower-tier or unverified items are displayed transparently in "Other Opportunities" with `rank = null`.
   - Generates deterministic, explainable rationales and confidence ratings (`high`, `medium`, `low`).

5. **ASA — Application Strategy Agent (`backend/agents/asa.py`):**
   - Formulates tailored Statement of Purpose (SOP) drafts for the top-ranked recommendation.
   - Structures content into academic trajectory, targeted institutional alignment, and future impact.
   - Builds actionable application checklists with deadlines, missing documentation alerts, and verification warnings.
   - Grounds every statement in verbatim evidence excerpts without fabricating achievements.

---

## 3. Technology Stack

- **Frontend:**
  - React 19 with TypeScript
  - Vite 8 development and production bundler
  - Vanilla CSS design system with responsive layouts, dark glassmorphism, and micro-animations
  - Lucide React icons
- **Backend:**
  - Python 3.12 & FastAPI
  - Uvicorn ASGI server
  - Pydantic v2 for strict runtime schema validation
  - HTTPX for asynchronous and synchronous network requests
  - PyPDF for safe document ingestion
  - python-dotenv for environment configuration management
- **Security & Networking:**
  - Custom SSRF defense module with socket-level IP validation, connection pinning, and private network rejection (RFC 1918, link-local, cloud metadata)
- **Search Provider:**
  - Tavily AI Search API (`SEARCH_PROVIDER=tavily`) with offline mock fallback
- **Persistence:**
  - SQLite (`scholar_swarm.db`) with relational integrity, foreign key constraints, and JSON payload storage

---

## 4. Getting Started (Windows PowerShell Setup)

### Prerequisites
- Python 3.11 or 3.12 installed (`python --version`)
- Node.js 18+ and npm installed (`node --version`, `npm --version`)
- Git installed (`git --version`)

### Step 1: Clone the Repository
```powershell
git clone https://github.com/udaypratapchauhan/ScholarSwarm-AI.git
cd ScholarSwarm-AI
```

### Step 2: Configure Environment Variables
Copy the safe template `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

Open `.env` in your text editor and configure your search provider. To enable live internet research:
```ini
SEARCH_PROVIDER=tavily
SEARCH_API_KEY=your_actual_tavily_api_key_here
```
> **Security Notice:** `.env` is ignored by Git in `.gitignore`. Never commit or expose your live API key. If `SEARCH_API_KEY` is left blank, ScholarSwarm AI automatically operates in offline mock mode.

### Step 3: Install Backend Dependencies & Start Backend
Open a PowerShell terminal:
```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
Verify the backend is live:
- Health Check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Interactive API Docs (Swagger): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Step 4: Install Frontend Dependencies & Start Frontend
Open a second PowerShell terminal:
```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Open your browser to:
- Frontend UI: [http://127.0.0.1:5173/](http://127.0.0.1:5173/)

---

## 5. Verification, Testing & Building

### Running Backend Unit & Integration Tests
Execute the full 254-test suite:
```powershell
python -m pytest backend/tests/ -q
```
*The automated test suite runs hermetically with isolated mock fixtures to protect API quotas.*

### Building Frontend for Production
```powershell
npm --prefix frontend run build
```
Generates optimized, type-checked production bundles in `frontend/dist/`.

---

## 6. Live Search vs. Offline Mock Fallback

| Attribute | Live Search (`SEARCH_PROVIDER=tavily`) | Mock Fallback (`SEARCH_PROVIDER=mock`) |
|---|---|---|
| **Data Source** | Live internet search via Tavily Search API | Curated offline database (`MOCK_SCHOLARSHIP_POOL`) |
| **`is_mock` Flag** | `False` | `True` (strictly labeled on every record) |
| **Web Provenance** | Fetched from live university/agency servers | Pre-computed illustrative records |
| **Verification Tier** | Can achieve **T4**, T3, or T2 based on live checks | Fixed at **T1** (cannot claim official status) |
| **Top-5 Qualification** | Eligible if official domain + HTTP 200 verified | Ineligible by design (0 mock items in Top-5) |
| **Network Required** | Yes | No (works 100% offline) |

---

## 7. Evidence-Based Limitations & Ethical AI Guidelines

- **Discovery Does Not Equal Eligibility:** Finding a scholarship page through web search does not guarantee a student qualifies. Deadlines, departmental quotas, funding limits, and GPA scale conversions must be verified from official university publications.
- **Strict Evidence Standards:** ScholarSwarm AI never fabricates or pads recommendations. If only two opportunities meet rigorous T4 verification criteria, the platform displays exactly two Top-5 recommendations rather than falsely promoting unverified sources.
- **SSRF & Security Isolation:** All external links are pre-screened to prevent private network scanning and server-side request forgery before fetching.

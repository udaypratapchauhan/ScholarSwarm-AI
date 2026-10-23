# ScholarSwarm AI — Hackathon Submission

**Project Title:** ScholarSwarm AI — Evidence-First Multi-Agent Scholarship Research & Verification Platform  
**Repository URL:** [https://github.com/udaypratapchauhan/ScholarSwarm-AI](https://github.com/udaypratapchauhan/ScholarSwarm-AI)  
**Hackathon:** TetraNoodle AI Hackathon 2026

---

## 1. Problem & Proposed Solution

### The Problem
International students seeking higher education face immense obstacles finding scholarships:
- Search engines are flooded with commercial aggregators, dead links, and outdated deadlines.
- Conventional generative AI tools routinely hallucinate scholarship eligibility, inventing non-existent stipends and falsifying application requirements.
- Students confuse general university admissions criteria with strict scholarship eligibility, leading to rejected applications and wasted fees.
- Varying international grading scales (e.g., 4.0 vs 10.0 vs percentage systems) cause inaccurate qualification assessments.

### The Proposed Solution
ScholarSwarm AI solves this through a coordinated swarm of five autonomous agents. Rather than relying on ungrounded language model generation, every opportunity is discovered through live web search, verified via SSRF-safe page fetching, evaluated independently for admission and funding rules, ranked deterministically against configurable criteria, and transformed into a verified Statement of Purpose outline.

---

## 2. Agent Collaboration & Actual Web/API Integration

The five specialized agents execute in sequential orchestration:
1. **Student Profile Agent (SPA):** Ingests resumes/transcripts (PDF/DOCX) or structured profile input, extracting GPA, scale, degrees, standardized test scores, and explicit vs. inferred skills.
2. **Opportunity Research Agent (ORA):** Formulates targeted search queries and queries the **live Tavily Search API** (with offline mock fallback). Deduplicates URLs and enforces destination country matching.
3. **Eligibility & Evidence Verification Agent (EEVA):** Fetches candidate pages using an SSRF-safe client with DNS pre-resolution and connection pinning. Classifies domain trust (`official_provider`, `reliable_secondary`, `aggregator`, `unknown`), independently evaluates admission vs scholarship rules, and assigns evidence tiers (**T1** to **T4**).
4. **Matchmaking & Ranking Agent (MRA):** Evaluates multi-factor alignment using configurable weights (`config/scoring_weights.json`). Strictly requires **T4 official-provider verification** for Top-5 recommendations, placing lower-tier results in "Other Opportunities".
5. **Application Strategy Agent (ASA):** Generates an evidence-grounded Statement of Purpose (SOP) draft and actionable application checklist tied directly to verified criteria.

---

## 3. Most Interesting Experiment

**Transitioning from Mock Discovery to Live Tavily Search & Decoupling Discovery from Verification:**
In early milestones, the system operated on a curated mock pool where every item was explicitly labeled `is_mock=True` and restricted to Tier T1. During final smoke testing, we integrated the live Tavily AI Search API (`SEARCH_PROVIDER=tavily`). 

The most revealing outcome was observing how real internet data behaves:
- In our live search test for a Computer Science master's student profile, Tavily successfully returned **10 real candidates** from live web sources.
- However, web discovery did not equal official verification. Out of 10 live candidates, **only 2** came from authoritative official government/university domains (`canada.ca` and `nserc-crsng.canada.ca`) that were successfully fetched and contained grounded verbatim evidence.
- The remaining 8 candidates came from secondary sources, educational aggregators, or sites protected by Cloudflare WAF.
- Rather than blindly trusting search engine snippets or promoting unverified listings, the verification engine correctly placed the 2 official candidates in Top-5 recommendations (T4) and assigned the remaining 8 candidates to "Other Opportunities" (T2 and T1). This demonstrated that search discovery and authoritative evidence verification must always remain distinct.

*(Note: These figures represent an actual test snapshot for a specific test profile and destination preference, not a universal guarantee for all academic fields.)*

---

## 4. Biggest Technical Challenge

**SSRF-Safe Official Source Verification and Preventing Hallucinated Matches:**
Autonomous agents fetching live URLs from the internet present significant security and reliability risks:
- **Server-Side Request Forgery (SSRF):** Malicious or misconfigured URLs could target internal loopback addresses, private networks (RFC 1918), or cloud metadata services (`169.254.169.254`). We addressed this by building a dedicated security client that pre-resolves DNS, validates all IPv4 and IPv6 addresses against private CIDR blocks, pins the TCP socket to the validated IP to prevent DNS rebinding attacks, and limits manual redirects to 3 hops.
- **Enforcing Anti-Hallucination Constraints:** Preventing unverified opportunities from polluting the recommendations required strict architectural barriers: mock records are permanently prohibited from reaching T3 or T4, and MRA strictly refuses to assign a Top-5 rank to any candidate lacking T4 official-provider evidence.

---

## 5. Test Evidence & Validation

All tests and builds were executed and verified locally:
- **Backend Test Suite:** **254 passed, 0 failed** in `python -m pytest backend/tests/ -q` (100% passing across schema validation, SSRF defenses, SQLite persistence, and multi-agent pipeline orchestration).
- **Frontend Production Build:** Built cleanly with `tsc -b && vite build` in 1.97s (0 errors, 0 warnings).
- **Backend Health Check:** `http://127.0.0.1:8000/api/health` returns HTTP 200 `{"status": "healthy", "database": "connected", "version": "0.1.0"}`.
- **Frontend Server:** Responding HTTP 200 at `http://127.0.0.1:5173/`.
- **Live Search Verification:** Live Tavily search executed successfully, returning real URLs, titles, and snippets without credentials leakage.

---

## 6. Five-Minute Demo Video Recording Outline

| Time | Segment | Key Talking Points & Actions |
|---|---|---|
| **0:00 – 0:45** | **Introduction & Problem** | Explain the scholarship search problem: hallucinated requirements, unverified aggregators, and conflated admissions vs funding criteria. |
| **0:45 – 1:30** | **Architecture Overview** | Walk through the 5-agent swarm (SPA → ORA → EEVA → MRA → ASA) and the strict evidence tiering model (T1 to T4). |
| **1:30 – 2:30** | **Live Ingestion & Profile Extraction** | Submit student profile in UI. Show SPA extracting GPA, scale, degree target, and explicit skills. Show live event timeline streaming in real time. |
| **2:30 – 3:45** | **Live Research & Official Verification** | Trigger research pipeline. Show ORA discovering live opportunities via Tavily Search API. Show EEVA performing SSRF-safe verification and classifying official domains versus aggregators. |
| **3:45 – 4:30** | **Explainable Ranking & SOP Generation** | Inspect Top-5 recommendations: show why official T4 candidates qualified and why unverified aggregators received `rank = null`. Open the generated Statement of Purpose draft from ASA. |
| **4:30 – 5:00** | **Conclusion & Security Architecture** | Highlight offline mock fallback, SSRF defense with connection pinning, and production readiness. |

---

## 7. Deliverables Checklist

- [x] Working multi-agent codebase (SPA, ORA, EEVA, MRA, ASA)
- [x] Live web search integration (Tavily AI Search) with offline mock fallback
- [x] SSRF security engine with DNS pre-resolution and connection pinning
- [x] React 19 + TypeScript + Vite frontend with real-time event timeline
- [x] SQLite persistence layer with relational integrity
- [x] Automated test suite (254 passing tests)
- [x] Complete project documentation (`README.md`, `ARCHITECTURE.md`, `SUBMISSION.md`)
- [x] Safe configuration template (`.env.example`) with secrets excluded from version control
- [ ] **Demo Video URL:** *[Insert final 5-minute video recording URL here before final submission form submission]*

---

## 8. Limitations & Future Roadmap

- **Admissions Portal Access:** Many university portals require student authentication or dynamic JavaScript rendering to view department-specific funding quotas. Adding headless browser verification with session support will unlock deeper verification.
- **Multilingual Verification:** Non-English national scholarship portals (e.g., in Japan, Germany, and France) would benefit from automated translation pipelines prior to requirement extraction.
- **Automated Deadline Sync:** Future iterations will support calendar export (iCal / Google Calendar) directly from verified application timelines.

# Compliance Workflow Tool — Equipment Qualification Web App (MVP)

> **Note:** This repository currently contains only this README. The source code will be published here once the MVP is feature-complete.

---

A Streamlit-based web application for managing the full equipment qualification lifecycle in regulated industries (pharma, biotech, medtech). It guides teams from loading standardized User Requirements Specifications (URS) with manual extensions through risk assessment, design qualification (DQ), and qualification execution (xQ), generating audit-ready PDF documents along the way.

---

## What problem does this solve?

Equipment qualification in regulated environments (GxP, FDA 21 CFR Part 11, Annex 11) is documentation-heavy and error-prone when managed in Word/Excel manually. This tool provides a structured, workflow-driven interface that:

- Ensures all requirements are captured and traceable
- Links URS requirements to risk items and qualification tests automatically
- Enforces phase-gate progression so teams can't skip steps
- Generates compliant PDF documents ready for review and approval

---

## Current Status (February 2026)

The MVP is actively in development. The following pages and features are working:

| Module | Status | Description |
|---|---|---|
| Project Overview (Dashboard) | Working | Overview of all assets and their current phase |
| URS Composer | Working | Catalog-based requirement assignment, custom URS, PDF export |
| Risk Assessment (FMEA) | Working | Risk catalog, severity/probability scoring, mitigation tracking |
| Design Qualification (DQ) | Working | DQ checklist linked to URS requirements |
| Qualification Plan (xQ Plan) | Under Construction | Test planning linked to URS/risk items |
| Qualification Execution (xQ) | Under Construction | Test execution with pass/fail recording |

---

## Screenshots

### Dashboard — Project Overview

> *Screenshot: The landing page lists all assets/projects with their current qualification phase. Each row shows sortable columns for location and utilities, plus quick-access buttons to jump into the active phase.*

![Project Overview](screenshots/project_overview.png)

---

### URS Composer — Requirement Assignment

> *Screenshot: Requirements are loaded from a structured catalog, grouped by subchapter: Safety & Control, Components, Software, etc. and assigned to the asset. Custom requirements can be added inline.*

![URS Composer](screenshots/URS.png)

---

### Risk Assessment — FMEA

> *Screenshot: Each URS requirement has associated risk items. Severity and probability are scored to calculate a risk level (Low / Medium / High), with mitigation status tracking.*

![Project Overview](screenshots/Risk_assignment.png)

---

### Qualification Execution — Test Results

> *Screenshot: Testers record pass/fail results per test step. The form is locked once the phase is complete.*

<!-- Add screenshot here: xq_execution.png -->

---

### PDF Export

> *Screenshot: Generated qualification document with header, approval block, and structured requirement tables — ready for review.*

<!-- Add screenshot here: pdf_export.png -->

---

## Workflow

```
New Project
     │
     ▼
1. URS  ──── Assign standardized requirements from catalog, add custom items
     │
     ▼
2. Risk ──── FMEA: score severity × probability, define mitigations
     │
     ▼
3. DQ  ──── Design Qualification checklist
     │
     ▼
4. xQ Plan ── Define qualification test cases
     │
     ▼
5. xQ Execution ── Record test results (pass / fail)
     │
     ▼
6. Done ── All sections read-only, documents archived
```


---

## Tech Stack

- **Frontend/UI**: [Streamlit](https://streamlit.io/)
- **Data Layer**: currently Excel files (will be changed soon)
- **Language**: Python 3.11+

---

## Roadmap

- [ ] Finish xQ Phases and fix bugs
- [ ] Replace Excel data layer with SQLite
- [ ] User authentication and role-based access 
- [ ] Cloud deployment (Streamlit Community Cloud)

---

## About

Built as a personal project to solve a real pain point in generating highly standardized URS with relating and repeating risks and qualification tasks. Minimizes the manual workforce by creating standardized documents. 

Feedback and ideas welcome — open an issue or reach out directly.

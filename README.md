<!--
# ==============================================================================
# File: README.md
# Description: Primary documentation and bootstrap instructions for the LifeOS Django repository
# Component: Documentation
# Version: 5.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-27
# ==============================================================================
-->
# LifeOS Django (V5.0)

LifeOS Django is a stability-first, single-owner personal operating system designed to run locally. Built around a unified DRY data model, it consolidates work management (Epics, Projects, Tasks) and academic learning trackers (Specializations, Courses, Modules, LearningTasks) into a cohesive relational structure. 

The application utilizes server-rendered Django templates, HTMX for partial-page reactivity, and is backed by PostgreSQL or local SQLite databases (user-configurable).

---

## Key Features

*   **Unified DRY Data Model**: Combines work and study hierarchies into a type-discriminated `WorkspaceContainer` and actionable leaf-node `ExecutionItem` records.
*   **Consolidated Focus Engine**: Universal timing controls to track focus. Supports manual time overrides (`extra_actual_seconds`) and recursive, chronological container timing roll-ups.
*   **Fuzzy Scheduling Engine & Time Block Optimizer**: A hybrid scheduling workflow combining:
    *   *Natural Language Parsing*: A local Small Language Model (Ollama) parses unstructured constraints (dates, priorities, urgency) into structured JSON.
    *   *Deterministic Interval Solver*: A greedy solver fits task items into free slots in your schedule, taking your defined Availability Windows and synced Google Calendar events (blocking/non-blocking) into account.
*   **Backlog Explorer & Multi-Tag Filtering**: A collapsible tree explorer with parent reassignment, task status override options, and a checkbox filter supporting positive tag matching, tag exclusions, and untagged item filtering.
*   **Inbox Triage Center**: Triages both orphaned tasks and newly created containers (e.g., Epics and Projects), defaulting items without dates into a Backlog status.
*   **Dynamic Configurations**: Edit database backend URLs directly in the settings (updates `.env` with a server restart warning banner) and configure timezones using a searchable, auto-detecting IANA timezone selector.
*   **Layered Security**: Enforces strong `Argon2` password hashing and a strict single-owner access policy via middleware that blocks and redirects unauthenticated or non-owner requests.

---

## Directory Index

*   [USER_GUIDE.md](USER_GUIDE.md) - Operations guide detailing server startup, layouts, and day-to-day use.
*   [docs/LifeOS-SRS.md](docs/LifeOS-SRS.md) - Software Requirements Specification outlining system functional specs from versions 1.0 to 5.0.
*   [docs/TECHNICAL_DOCS.md](docs/TECHNICAL_DOCS.md) - Technical Architecture guide outlining DB schemas, models, scheduling solver logic, and infrastructure.
*   [validate_sandbox.py](validate_sandbox.py) - Environment verification script check.

---

## Quick Start

### 1. Prerequisite Verification
Run the verification utility to verify that your system runtimes (`python3`, `git`, `pip3`) are configured correctly:
```powershell
python validate_sandbox.py
```

### 2. Dependency Installation
Create and activate your Python virtual environment, then install requirements:
```powershell
# Activate venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Database Migrations
Generate and apply database migrations to setup the schema:
```powershell
python manage.py makemigrations lifeos_app
python manage.py migrate
```

### 4. Create Owner Superuser
Configure your secure owner credentials:
```powershell
python manage.py createsuperuser
```

### 5. Running the Application
Boot up the local development server:
```powershell
python manage.py runserver
```
Navigate to [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## Running the Automated Test Suite

Validate system components, authentication middleware, and timing models:
```powershell
python manage.py test
```
*Runs the consolidated test suite including core models, focus widgets, calendar sync solvers, and triage cycle check validations.*

<!--
# ==============================================================================
# File: USER_GUIDE.md
# Description: User guide explaining application startup, settings, layouts, and V5.0 features
# Component: Documentation
# Version: 5.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-27
# ==============================================================================
-->
# LifeOS Django: User Guide (V5.0)

Welcome to **LifeOS Django V5.0**—a stability-first personal operating system built around a unified DRY data model. This guide outlines how to start, navigate, configure, and utilize the application's core systems.

---

## 1. Starting the Application

Since LifeOS Django is designed as a single-user local system, you run the service from your local workstation using the standard Django development server.

### Steps to Run
1. Open a terminal (PowerShell or Command Prompt) and navigate to the project directory:
   ```powershell
   cd "path/to/LifeOS_Django"
   ```
2. Activate the python virtual environment:
   ```powershell
   .venv\Scripts\activate
   ```
3. Run migrations to ensure your schema is up to date:
   ```powershell
   python manage.py migrate
   ```
4. Boot up the server:
   ```powershell
   python manage.py runserver
   ```
   *By default, the server will bind to port `8000` on localhost.*
5. Open your web browser and navigate to:
   [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 2. Navigation Sidebar Layout

LifeOS V5.0 features a persistent, space-efficient side navigation bar structure:
*   **The Top Command Bar**: Contains quick system actions (owner profile badge, quick brain dump entry field, and standard log out options).
*   **The Left Vertical Sidebar**: Gives you instant access to view directories: Dashboard, Inbox Triage, Backlog Explorer, Planner, Analytics, and Academy.
*   **Collapsible Design**: You can collapse the sidebar using the toggle chevron button in the bottom left corner. The collapsed state is persisted in your browser's `localStorage` so it remains unchanged between page loads.

---

## 3. Global Quick Entry ("Brain Dump")

Use the text field in the top bar to capture ideas immediately:
1. Locate the input box labeled **"Brain dump..."** on the right side of the header.
2. Enter the title of your task or container.
3. Select its type:
    *   **Task**: Sent to the Inbox queue as an unfiled execution item.
    *   **Epic / Project / Specialization / Course / Module**: Instantiates a Workspace Container of that type.
4. Press `Enter` or click the `+` button to submit.

---

## 4. Inbox Triage Center

New ideas are placed into the Triage Center for organization. Unlike older versions, **LifeOS V5.0 supports triaging both Execution Items and Workspace Containers**.

### Processing Items
1. Navigate to **Inbox Triage** from the sidebar.
2. For each card:
    *   **Scope / Parent**: Nest the task under a parent Container, or link it to another Task to establish subtask connections. For new Containers, you can optionally define a parent Container.
    *   **Domain & PARA Category**: Select the target life domain and PARA category.
    *   **Status Target**: Direct it to `Planned` or `Backlog`.
    *   **Default Status Rule**: If you do not assign a start or due date, the item will intelligently default to **Backlog** status when processed to prevent clutter.
3. Click **Process & File** (or **Process Container**) to complete triaging.

---

## 5. Backlog Explorer (Tree View)

The **Backlog Explorer** provides a collapsible tree showing all of your active folders, projects, tasks, and subtasks.

### Advanced Features in V5.0:
*   **Multi-Tag Filtering**: Use the tag filter checkboxes at the top of the explorer to narrow down items:
    *   Filter by single or multiple tags (only items matching all selected tags are shown).
    *   Exclude tags (hide items matching selected tags).
    *   Filter for untagged items.
*   **Parent Reassignment**: Open the edit modal (pencil icon) on any Container or Execution Item. You can now re-assign the parent container relationship to restructure your hierarchy.
*   **Status Override**: If you accidentally complete an item, opening its edit form allows you to change the status back to an active state (like *In Progress* or *Planned*), which automatically resets the completion flag in the database.
*   **Dates Display**: Start, end, and due dates, along with active tags and urgency levels, are displayed directly on the explorer cards.

---

## 6. Planner, Availability Blocks, and SLM Scheduling

The Planner (`/planner/`) houses your automated calendar and scheduling engines.

### Dynamic Availability Blocks & Hard Busy Blocks
*   Configure **Availability Windows** (e.g. "Work Hours", "Weekend Hobby") in Settings.
*   Integrate **Google Calendar** feeds to load busy times. You can toggle calendar items between **blocking** (tasks cannot overlap) or **non-blocking** (tasks can overlap).

### Automated SLM Scheduler
1. Enter scheduling constraints in plain language in the natural language planning input.
2. Click **Optimize Timeline**. The local Small Language Model (Ollama) will parse your request into temporal bounds, and the deterministic solver will generate task schedules around your availability blocks and calendar events.

---

## 7. Configuration Settings

The Settings panel (`/settings/`) allows you to tune system parameters:
*   **Database Custom Path**: Input a local SQLite path or PostgreSQL connection URL.
    > [!WARNING]
    > Changing the database URL string rewrites the local `.env` environment file. A warning banner will display on screen; you must restart the Django server application to load the new database connections.
*   **IANA Timezones**: A searchable dropdown list for setting timezones, with auto-detection.
*   **Domain Manager**: Create, rename, or delete life domains, toggle their custom colors/icons, or mark them as "Academy" domains to aggregate learning metrics separately.

# ==============================================================================
# File: lifeos_app/services/cmd.py
# Description: Command palette mode detection and execution (ENG-CMD)
# Component: Services / Command Engine
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Cmd+K palette — capture, go, do, and search dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.urls import reverse

from lifeos_app.models import (
    AppSettings,
    ExecutionItem,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.capture import CapturePreview, parse_capture
from lifeos_app.services.focus import complete_focus, pause_focus, start_focus
from lifeos_app.services.scheduler import run_scheduler
from lifeos_app.services.tags import resolve_tag
from lifeos_app.services.templates_workspace import TemplatePreview, apply_template, preview_template
from lifeos_app.services.today import clear_today, plan_today
GO_ALIASES: dict[str, str] = {
    "home": "home",
    "h": "home",
    "inbox": "canvas-inbox",
    "i": "canvas-inbox",
    "matrix": "canvas-matrix",
    "m": "canvas-matrix",
    "overview": "canvas-overview",
    "o": "canvas-overview",
    "plan": "canvas-plan",
    "planner": "canvas-plan",
    "board": "canvas-board",
    "boards": "canvas-board",
    "academy": "canvas-academy",
    "analytics": "canvas-analytics",
    "settings": "canvas-settings",
    "bulk": "canvas-bulk",
    "import": "canvas-bulk",
}


@dataclass
class CmdPreview:
    """Unified palette preview for any detected mode."""

    mode: str  # capture | go | do | search
    raw: str
    summary: str = ""
    redirect_url: str | None = None
    warnings: list[str] = field(default_factory=list)
    capture: CapturePreview | None = None
    template: TemplatePreview | None = None
    matches: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "raw": self.raw,
            "summary": self.summary,
            "redirect_url": self.redirect_url,
            "warnings": self.warnings,
            "capture": self.capture.as_dict() if self.capture else None,
            "template": self.template.as_dict() if self.template else None,
            "matches": self.matches,
        }


def _tz_name() -> str:
    try:
        return AppSettings.get_solo().timezone or "UTC"
    except Exception:
        return "UTC"


def detect_mode(raw: str) -> tuple[str, str]:
    """Return (mode, remainder) from palette input."""
    text = raw.strip()
    lower = text.lower()
    if lower.startswith("go "):
        return "go", text[3:].strip()
    if lower.startswith("g "):
        return "go", text[2:].strip()
    if lower.startswith("save view"):
        return "do", text
    if lower.startswith("template apply"):
        return "do", text
    if lower.startswith("focus "):
        return "do", text
    if lower.startswith("complete "):
        return "do", text
    if lower in ("pause", "pause focus"):
        return "do", text
    if lower == "plan today" or lower.startswith("plan today "):
        return "do", text
    if lower == "clear today":
        return "do", text
    if lower in ("schedule", "schedule run", "run schedule"):
        return "do", text
    if lower.startswith("search "):
        return "search", text[7:].strip()
    return "capture", text


def preview_command(raw: str) -> CmdPreview:
    """Build a debounced palette preview."""
    from lifeos_app.services.saved_views import build_view_url, get_view

    mode, remainder = detect_mode(raw)
    if not raw.strip():
        return CmdPreview(mode="capture", raw=raw, summary="Type to capture, go, or do…")

    if mode == "go":
        parts = remainder.split()
        head = parts[0].lower() if parts else ""
        if head == "view":
            slug = parts[1] if len(parts) > 1 else ""
            view = get_view(slug) if slug else None
            if view:
                return CmdPreview(
                    mode="go",
                    raw=raw,
                    summary=f"Open view “{view.title}” → {view.target_surface}",
                    redirect_url=build_view_url(view),
                )
            return CmdPreview(
                mode="go",
                raw=raw,
                summary=f"Unknown view: {slug or '(empty)'}",
                warnings=[f"No saved view with slug {slug!r}."],
            )
        url_name = GO_ALIASES.get(head)
        if url_name:
            return CmdPreview(
                mode="go",
                raw=raw,
                summary=f"Navigate → {head}",
                redirect_url=reverse(url_name),
            )
        return CmdPreview(
            mode="go",
            raw=raw,
            summary=f"Unknown destination: {head or '(empty)'}",
            warnings=[f"Unknown go target: {head!r}"],
        )

    if mode == "do":
        lower = remainder.lower()
        if lower.startswith("save view"):
            name = remainder[9:].strip() if lower.startswith("save view ") else ""
            # strip optional leading "view "
            if name.lower().startswith("view "):
                name = name[5:].strip()
            return CmdPreview(
                mode="do",
                raw=raw,
                summary=f"Save current facets as view “{name or '(name required)'}”",
                warnings=[] if name else ["Provide a view name."],
            )
        if lower.startswith("template apply"):
            slug = remainder[15:].strip() if lower.startswith("template apply ") else ""
            tpl = preview_template(slug)
            return CmdPreview(
                mode="do",
                raw=raw,
                summary=tpl.message if tpl.ok else f"Unknown template: {slug or '(empty)'}",
                warnings=tpl.warnings,
                template=tpl,
            )
        if lower in ("pause", "pause focus"):
            return CmdPreview(mode="do", raw=raw, summary="Pause active focus session")
        if lower.startswith("focus "):
            query = remainder[6:].strip()
            matches = _search_items(query, limit=5)
            return CmdPreview(
                mode="do",
                raw=raw,
                summary=f"Start focus: {query or '(pick item)'}",
                matches=matches,
                warnings=[] if matches else ["No matching items."],
            )
        if lower.startswith("complete "):
            query = remainder[9:].strip()
            matches = _search_items(query, limit=5)
            return CmdPreview(
                mode="do",
                raw=raw,
                summary=f"Complete: {query or '(pick item)'}",
                matches=matches,
                warnings=[] if matches else ["No matching items."],
            )
        if lower == "plan today" or lower.startswith("plan today "):
            q = remainder[10:].strip() if lower.startswith("plan today ") else ""
            return CmdPreview(
                mode="do",
                raw=raw,
                summary=f"Plan today{': ' + q if q else ' (top priority items)'}",
            )
        if lower == "clear today":
            return CmdPreview(mode="do", raw=raw, summary="Clear #today links")
        if lower in ("schedule", "schedule run", "run schedule"):
            return CmdPreview(mode="do", raw=raw, summary="Run auto-scheduler (greedy fit)")

    if mode == "search":
        matches = _search_items(remainder, limit=8)
        return CmdPreview(
            mode="search",
            raw=raw,
            summary=f"Search: {remainder}",
            matches=matches,
        )

    cap = parse_capture(remainder, tz_name=_tz_name())
    summary_bits = [cap.title]
    if cap.container_slug:
        summary_bits.append(f"→ #{cap.container_slug}")
    if cap.tag_slugs:
        summary_bits.append(" ".join(f"@{t}" for t in cap.tag_slugs))
    if cap.recurrence and not cap.recurrence.ambiguous:
        summary_bits.append(f"↻ {cap.recurrence.rrule_text}")
    return CmdPreview(
        mode="capture",
        raw=raw,
        summary=" · ".join(summary_bits),
        warnings=cap.warnings,
        capture=cap,
    )


def _search_items(query: str, limit: int = 8) -> list[dict[str, Any]]:
    if not query:
        return []
    qs = (
        ExecutionItem.objects.filter(is_deleted=False)
        .exclude(status=SystemEnums.ItemStatus.COMPLETED)
        .filter(title__icontains=query)
        .order_by("-updated_at")[:limit]
    )
    return [{"id": i.pk, "title": i.title, "status": i.status} for i in qs]


@dataclass
class CmdCommitResult:
    ok: bool
    message: str = ""
    redirect_url: str | None = None
    item_id: int | None = None
    refresh_fragments: bool = True


@transaction.atomic
def commit_capture(preview: CapturePreview) -> CmdCommitResult:
    """Create item from capture preview."""
    from lifeos_app.services.recurrence import attach_recurrence

    if not preview.title.strip():
        return CmdCommitResult(ok=False, message="Title required.")

    defaults = {
        "status": preview.status,
        "priority": preview.priority or SystemEnums.PriorityLevel.NORMAL,
        "urgency": preview.urgency or SystemEnums.UrgencyLevel.NORMAL,
        "due_at": preview.due_at,
        "fuzzy_timeframe": preview.fuzzy_timeframe,
    }
    if preview.estimated_minutes:
        defaults["estimated_minutes"] = preview.estimated_minutes
    item = ExecutionItem.objects.create(title=preview.title.strip(), **defaults)

    inbox_container = WorkspaceContainer.objects.filter(slug="inbox").first()
    container = None
    if preview.container_slug:
        container = WorkspaceContainer.objects.filter(slug=preview.container_slug).first()

    if container:
        ItemContainerLink.objects.create(item=item, container=container, is_primary=True)
    elif inbox_container:
        ItemContainerLink.objects.create(item=item, container=inbox_container, is_primary=False)

    for slug in preview.tag_slugs:
        item.tags.add(resolve_tag(slug))

    message = f"Captured: {item.title}"
    if preview.recurrence and not preview.recurrence.ambiguous and preview.recurrence.freq:
        rule = attach_recurrence(item, preview.recurrence)
        if rule and rule.next_occurrence_at:
            message = (
                f"Captured: {item.title} · repeats {rule.rrule_text} "
                f"(next {rule.next_occurrence_at:%a %H:%M})"
            )
            item.refresh_from_db()

    if item.due_at:
        from lifeos_app.services.reminders import rearm_due_reminders

        rearm_due_reminders(item)

    return CmdCommitResult(ok=True, message=message, item_id=item.pk)


def commit_command(
    raw: str,
    selected_item_id: int | None = None,
    *,
    view_surface: str = "",
    view_query_string: str = "",
) -> CmdCommitResult:
    """Execute palette input."""
    from lifeos_app.services.saved_views import params_from_query_string, save_view

    preview = preview_command(raw)
    mode, remainder = detect_mode(raw)

    if mode == "go" and preview.redirect_url:
        return CmdCommitResult(ok=True, message="Navigating…", redirect_url=preview.redirect_url)

    if mode == "do":
        lower = remainder.lower()
        if lower.startswith("save view"):
            name = remainder[9:].strip() if lower.startswith("save view ") else ""
            if name.lower().startswith("view "):
                name = name[5:].strip()
            surface = (view_surface or SystemEnums.SavedViewSurface.MATRIX).strip().lower()
            result = save_view(
                title=name,
                target_surface=surface,
                query_params=params_from_query_string(view_query_string),
            )
            return CmdCommitResult(
                ok=result.ok,
                message=result.message,
                refresh_fragments=False,
                redirect_url=None,
            )
        if lower.startswith("template apply"):
            slug = remainder[15:].strip() if lower.startswith("template apply ") else ""
            result = apply_template(slug)
            redirect = reverse("canvas-matrix") if result.ok else None
            return CmdCommitResult(
                ok=result.ok,
                message=result.message,
                refresh_fragments=False,
                redirect_url=redirect,
            )
        if lower in ("pause", "pause focus"):
            result = pause_focus()
            return CmdCommitResult(
                ok=result.ok,
                message=result.message,
                refresh_fragments=result.ok,
            )
        if lower.startswith("focus "):
            item = _resolve_item(remainder[6:].strip(), selected_item_id)
            if not item:
                return CmdCommitResult(ok=False, message="No matching item to focus.")
            result = start_focus(item)
            return CmdCommitResult(
                ok=result.ok,
                message=result.message,
                refresh_fragments=result.ok,
            )
        if lower.startswith("complete "):
            item = _resolve_item(remainder[9:].strip(), selected_item_id)
            if not item:
                return CmdCommitResult(ok=False, message="No matching item to complete.")
            result = complete_focus(item)
            return CmdCommitResult(ok=result.ok, message=result.message, refresh_fragments=result.ok)
        if lower == "plan today" or lower.startswith("plan today "):
            q = remainder[10:].strip() if lower.startswith("plan today ") else ""
            result = plan_today(query=q)
            return CmdCommitResult(ok=result.ok, message=result.message, refresh_fragments=result.ok)
        if lower == "clear today":
            result = clear_today()
            return CmdCommitResult(ok=result.ok, message=result.message, refresh_fragments=result.ok)
        if lower in ("schedule", "schedule run", "run schedule"):
            result = run_scheduler()
            return CmdCommitResult(
                ok=result.ok,
                message=result.message,
                refresh_fragments=result.ok,
                redirect_url=reverse("canvas-plan") if result.ok else None,
            )

    if mode == "capture" and preview.capture:
        return commit_capture(preview.capture)

    return CmdCommitResult(ok=False, message="Nothing to execute.")


def _resolve_item(query: str, selected_item_id: int | None) -> ExecutionItem | None:
    if selected_item_id:
        return ExecutionItem.objects.filter(pk=selected_item_id, is_deleted=False).first()
    if not query:
        return None
    return (
        ExecutionItem.objects.filter(is_deleted=False, title__icontains=query)
        .exclude(status=SystemEnums.ItemStatus.COMPLETED)
        .order_by("-updated_at")
        .first()
    )

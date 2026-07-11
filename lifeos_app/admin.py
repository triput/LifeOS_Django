# ==============================================================================
# File: lifeos_app/admin.py
# Description: Django Admin Inspection HUD for LifeOS V2 domain models
# Component: Core / Admin
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Raw database inspection HUD — single-owner admin configuration."""

from django.contrib import admin

from .models import (
    AppSettings,
    CalendarEvent,
    CalendarIntegration,
    SyncedCalendar,
    Certification,
    DomainCategory,
    ExecutionItem,
    FocusSession,
    ItemContainerLink,
    ItemDependencyLink,
    RecurrenceRule,
    ReminderDispatch,
    SavedView,
    ScheduledAllocation,
    StabilitySnapshot,
    Tag,
    TimeAvailabilityBlock,
    WorkspaceContainer,
    WorkspaceTemplate,
    WorkspaceTemplateNode,
)


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("pk", "timezone", "notifications_enabled", "daily_completion_target", "updated_at")
    fieldsets = (
        (
            "Google Calendar OAuth",
            {
                "fields": (
                    "google_oauth_client_id",
                    "google_oauth_client_secret",
                    "google_oauth_redirect_uri",
                    "calendar_push_enabled",
                ),
                "description": (
                    "OAuth client credentials from Google Cloud Console → Credentials → "
                    "Create OAuth client ID → Web application. "
                    "Values here override GOOGLE_OAUTH_* in .env when both are set. "
                    "Leave redirect URI blank to auto-detect from your LifeOS URL."
                ),
            },
        ),
        (
            "Microsoft Calendar OAuth",
            {
                "fields": (
                    "microsoft_oauth_client_id",
                    "microsoft_oauth_client_secret",
                    "microsoft_oauth_redirect_uri",
                ),
                "description": (
                    "App registration in Azure Entra ID → Authentication → Web redirect URI. "
                    "API permission: Microsoft Graph → Calendars.Read. "
                    "Values override MICROSOFT_OAUTH_* in .env when both are set."
                ),
            },
        ),
        (
            "Notifications",
            {"fields": ("notifications_enabled", "notification_channel", "notification_webhook_url", "notification_webhook_token")},
        ),
        (
            "General",
            {
                "fields": (
                    "timezone",
                    "theme_mode",
                    "pomodoro_duration",
                    "start_of_work_day",
                    "scheduler_buffer_minutes",
                ),
            },
        ),
    )


@admin.register(DomainCategory)
class DomainCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_academy", "is_active", "color")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("is_academy", "is_active")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "domain")
    list_filter = ("domain",)
    search_fields = ("name",)


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "credits_required", "credit_unit_type")
    search_fields = ("name", "provider")


class ItemContainerLinkInline(admin.TabularInline):
    model = ItemContainerLink
    extra = 0


class ItemDependencyLinkInline(admin.TabularInline):
    model = ItemDependencyLink
    fk_name = "from_item"
    extra = 0


@admin.register(WorkspaceContainer)
class WorkspaceContainerAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "container_type",
        "para_state",
        "domain",
        "is_archived",
        "updated_at",
    )
    list_filter = ("para_state", "domain", "container_type", "is_archived")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        ("Core Matrix", {"fields": ("title", "slug", "container_type", "parent", "order")}),
        ("Classification Lens", {"fields": ("para_state", "domain", "priority", "urgency", "is_archived")}),
        ("Academy", {"fields": ("provider", "credit_unit_type", "credits_earned", "certification")}),
        ("Links", {"fields": ("external_url", "tags")}),
        ("Notes", {"fields": ("notes", "extra_actual_seconds")}),
    )
    filter_horizontal = ("tags",)


@admin.register(ExecutionItem)
class ExecutionItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status",
        "priority",
        "urgency",
        "due_at",
        "estimated_minutes",
        "time_spent_seconds",
        "is_deleted",
    )
    list_filter = ("status", "priority", "urgency", "item_type", "is_deleted")
    search_fields = ("title", "notes")
    inlines = [ItemContainerLinkInline, ItemDependencyLinkInline]
    filter_horizontal = ("tags",)


@admin.register(ItemContainerLink)
class ItemContainerLinkAdmin(admin.ModelAdmin):
    list_display = ("item", "container", "is_primary", "pinned")
    list_filter = ("is_primary", "pinned")


@admin.register(ItemDependencyLink)
class ItemDependencyLinkAdmin(admin.ModelAdmin):
    list_display = ("from_item", "link_type", "to_item")
    list_filter = ("link_type",)


@admin.register(FocusSession)
class FocusSessionAdmin(admin.ModelAdmin):
    list_display = ("execution_item", "started_at", "ended_at", "duration_seconds", "end_reason")
    list_filter = ("end_reason",)


@admin.register(ScheduledAllocation)
class ScheduledAllocationAdmin(admin.ModelAdmin):
    list_display = ("execution_item", "start_at", "end_at", "score", "source", "external_event_id")
    list_filter = ("source",)


@admin.register(TimeAvailabilityBlock)
class TimeAvailabilityBlockAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "start_time", "end_time")


@admin.register(CalendarIntegration)
class CalendarIntegrationAdmin(admin.ModelAdmin):
    list_display = ("provider", "user_email", "sync_enabled", "last_sync_at", "last_sync_error", "updated_at")


@admin.register(SyncedCalendar)
class SyncedCalendarAdmin(admin.ModelAdmin):
    list_display = (
        "summary",
        "calendar_id",
        "integration",
        "sync_enabled",
        "is_primary",
        "color",
        "color_locked",
    )
    list_filter = ("sync_enabled", "is_primary", "color_locked")


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "source_calendar", "start_at", "end_at", "is_blocking", "is_all_day")
    list_filter = ("is_blocking", "is_all_day")
    search_fields = ("title", "description", "external_id")


@admin.register(RecurrenceRule)
class RecurrenceRuleAdmin(admin.ModelAdmin):
    list_display = (
        "execution_item",
        "freq",
        "byweekday",
        "starts_at",
        "ends_at",
        "next_occurrence_at",
        "active",
    )


@admin.register(ReminderDispatch)
class ReminderDispatchAdmin(admin.ModelAdmin):
    list_display = ("dedupe_key", "kind", "status", "fire_at", "sent_at", "execution_item")
    list_filter = ("kind", "status", "channel")
    search_fields = ("dedupe_key",)


@admin.register(StabilitySnapshot)
class StabilitySnapshotAdmin(admin.ModelAdmin):
    list_display = ("date", "band", "index_score", "completions_count", "focus_seconds", "streak_days")
    list_filter = ("band",)


@admin.register(SavedView)
class SavedViewAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "target_surface", "is_pinned", "is_archived")
    prepopulated_fields = {"slug": ("title",)}
    list_filter = ("target_surface", "is_pinned", "is_archived")


class WorkspaceTemplateNodeInline(admin.TabularInline):
    model = WorkspaceTemplateNode
    extra = 0
    fk_name = "template"


@admin.register(WorkspaceTemplate)
class WorkspaceTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "domain_hint", "para_hint", "is_active")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [WorkspaceTemplateNodeInline]


@admin.register(WorkspaceTemplateNode)
class WorkspaceTemplateNodeAdmin(admin.ModelAdmin):
    list_display = ("template", "title", "node_kind", "container_type", "item_type", "order")
    list_filter = ("node_kind", "template")

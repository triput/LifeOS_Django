# ==============================================================================
# File: lifeos_app/models.py
# Description: LifeOS V2 domain models — Node/Leaf schema and supporting engines
# Component: Core / Database Models
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""LifeOS V2 unified domain models.

Implements the adopted Alternate SRS §5 schema: WorkspaceContainer (Node),
ExecutionItem (Leaf), multi-home links, dependencies, focus sessions,
scheduling, notifications, stability, saved views, and curated templates.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SystemEnums:
    """Canonical categorical matrices for PARA, domain-adjacent axes, and priority."""

    class PARACategory(models.TextChoices):
        PROJECT = "PROJECT", _("Project (Active Velocity)")
        AREA = "AREA", _("Area (Maintenance)")
        RESOURCE = "RESOURCE", _("Resource (Knowledge Vault)")
        ARCHIVE = "ARCHIVE", _("Archive (Frozen State)")

    class PriorityLevel(models.IntegerChoices):
        CRITICAL = 1, _("P1 - Critical / Blocking")
        HIGH = 2, _("P2 - High / Next Action")
        NORMAL = 3, _("P3 - Normal / Routine")
        LOW = 4, _("P4 - Low / Backlog")

    class UrgencyLevel(models.TextChoices):
        IMMEDIATE = "IMMEDIATE", _("Immediate")
        HIGH = "HIGH", _("High")
        NORMAL = "NORMAL", _("Normal")
        LOW = "LOW", _("Low")

    class ContainerType(models.TextChoices):
        EPIC = "EPIC", _("Epic / Macro Project")
        PROJECT = "PROJECT", _("Project")
        SPRINT = "SPRINT", _("Development Sprint")
        SPECIALIZATION = "SPECIALIZATION", _("Academic Specialization")
        COURSE = "COURSE", _("Academic Course")
        MODULE = "MODULE", _("Course Module")
        LIST = "LIST", _("Operational List")
        INBOX = "INBOX", _("Global Inbox")

    class ItemType(models.TextChoices):
        TASK = "TASK", _("Task")
        SUBTASK = "SUBTASK", _("Subtask")
        LEARNING_TASK = "LEARNING_TASK", _("Learning Task")
        LIFE_ACTIVITY = "LIFE_ACTIVITY", _("Life Activity")

    class ItemStatus(models.TextChoices):
        INBOX = "INBOX", _("Inbox")
        BACKLOG = "BACKLOG", _("Backlog")
        PLANNED = "PLANNED", _("Planned")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        BLOCKED = "BLOCKED", _("Blocked")
        COMPLETED = "COMPLETED", _("Completed")

    class FuzzyTimeframe(models.TextChoices):
        NONE = "NONE", _("None")
        TODAY = "TODAY", _("Today")
        TOMORROW = "TOMORROW", _("Tomorrow")
        WEEKEND = "WEEKEND", _("Weekend")
        THIS_WEEK = "THIS_WEEK", _("This Week")
        THIS_MONTH = "THIS_MONTH", _("This Month")

    class ReminderKind(models.TextChoices):
        DUE_APPROACHING = "DUE_APPROACHING", _("Due Approaching")
        ALLOCATION_START = "ALLOCATION_START", _("Allocation Start")
        OVERDUE = "OVERDUE", _("Overdue")

    class ReminderDispatchStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        SNOOZED = "SNOOZED", _("Snoozed")
        CANCELLED = "CANCELLED", _("Cancelled")

    class DependencyLinkType(models.TextChoices):
        BLOCKS = "BLOCKS", _("Blocks")
        RELATES = "RELATES", _("Relates")

    class StabilityBand(models.TextChoices):
        STABLE = "STABLE", _("Stable")
        BEHIND = "BEHIND", _("Behind")
        OVERLOADED = "OVERLOADED", _("Overloaded")

    class FocusEndReason(models.TextChoices):
        PAUSE = "PAUSE", _("Pause")
        STOP = "STOP", _("Stop")
        COMPLETE = "COMPLETE", _("Complete")
        PREEMPTED = "PREEMPTED", _("Preempted")

    class AllocationSource(models.TextChoices):
        MANUAL = "MANUAL", _("Manual")
        SOLVER = "SOLVER", _("Solver")
        CALENDAR_PUSH = "CALENDAR_PUSH", _("Calendar Push")

    class CalendarProvider(models.TextChoices):
        GOOGLE = "google", _("Google Calendar")
        MICROSOFT = "microsoft", _("Microsoft 365 / Outlook")

    class SavedViewSurface(models.TextChoices):
        MATRIX = "matrix", _("Matrix")
        OVERVIEW = "overview", _("Overview")
        BOARD = "board", _("Board")

    class NotificationChannel(models.TextChoices):
        NTFY = "ntfy", _("ntfy")
        GOTIFY = "gotify", _("Gotify")
        RAW_JSON = "raw_json", _("Raw JSON")

    class WeatherProvider(models.TextChoices):
        AUTO = "auto", _("Auto (NWS in US, else Open-Meteo)")
        OPEN_METEO = "open_meteo", _("Open-Meteo")
        NWS = "nws", _("NWS (weather.gov)")
        OPENWEATHERMAP = "openweathermap", _("OpenWeatherMap")


# ---------------------------------------------------------------------------
# Settings & taxonomy
# ---------------------------------------------------------------------------


class AppSettings(models.Model):
    """Singleton owner preferences and engine policy knobs."""

    pomodoro_duration = models.PositiveIntegerField(default=25)
    start_of_work_day = models.TimeField(default="09:00:00")
    timezone = models.CharField(max_length=64, default="America/Phoenix")
    use_24h_time = models.BooleanField(default=False)
    use_imperial = models.BooleanField(default=True)
    location_name = models.CharField(max_length=255, default="Phoenix, AZ")
    latitude = models.FloatField(default=33.66, null=True, blank=True)
    longitude = models.FloatField(default=-112.34, null=True, blank=True)
    auto_detect_location = models.BooleanField(default=False)

    weather_provider = models.CharField(
        max_length=20,
        choices=SystemEnums.WeatherProvider.choices,
        default=SystemEnums.WeatherProvider.AUTO,
    )
    openweather_api_key = models.CharField(max_length=128, blank=True, default="")

    # Telemetry HUD color bands — exclusive upper bounds; defaults from services.telemetry.bands
    # Weather cutoffs stored in °C (DEF-P33-005). Catalog: 10 / 23.9 / 32.2 °C · Kp 3 / 5 / 7.
    weather_band_cold_max = models.FloatField(default=10.0)
    weather_band_moderate_max = models.FloatField(default=23.9)
    weather_band_warm_max = models.FloatField(default=32.2)
    kp_band_blue_max = models.FloatField(default=3.0)
    kp_band_green_max = models.FloatField(default=5.0)
    kp_band_yellow_max = models.FloatField(default=7.0)

    priority_weight = models.FloatField(default=1.5)
    urgency_weight = models.FloatField(default=2.0)
    slm_endpoint = models.CharField(max_length=255, default="http://localhost:11434/api/generate")
    enable_ai_scheduling = models.BooleanField(default=True)
    respect_child_dates_by_default = models.BooleanField(default=True)
    scheduler_buffer_minutes = models.PositiveIntegerField(default=10)
    calendar_push_enabled = models.BooleanField(
        default=False,
        help_text="P5-03: push LifeOS allocations to Google Calendar (requires reconnect for write scope).",
    )

    theme_mode = models.CharField(max_length=32, default="hybrid_dark")

    # Google Calendar OAuth client (ENG-CAL) — stored in DB, not git
    google_oauth_client_id = models.CharField(max_length=255, blank=True, default="")
    google_oauth_client_secret = models.CharField(max_length=255, blank=True, default="")
    google_oauth_redirect_uri = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Optional. Leave blank to auto-detect from the current site URL.",
    )

    # Microsoft Graph OAuth client (ENG-CAL-MS) — stored in DB, not git
    microsoft_oauth_client_id = models.CharField(max_length=255, blank=True, default="")
    microsoft_oauth_client_secret = models.CharField(max_length=255, blank=True, default="")
    microsoft_oauth_redirect_uri = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Optional. Leave blank to auto-detect from the current site URL.",
    )

    # Notification policy (ENG-NOTIFY)
    notifications_enabled = models.BooleanField(default=False)
    notification_channel = models.CharField(
        max_length=16,
        choices=SystemEnums.NotificationChannel.choices,
        default=SystemEnums.NotificationChannel.NTFY,
    )
    notification_webhook_url = models.URLField(blank=True, default="")
    notification_webhook_token = models.CharField(max_length=512, blank=True, default="")
    reminder_lead_minutes = models.PositiveIntegerField(default=15)
    reminder_second_lead_minutes = models.PositiveIntegerField(null=True, blank=True, default=1440)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    reminder_min_priority = models.IntegerField(
        choices=SystemEnums.PriorityLevel.choices,
        default=SystemEnums.PriorityLevel.NORMAL,
    )
    remind_backlog_with_due = models.BooleanField(default=False)
    remind_inbox_with_due = models.BooleanField(default=False)

    # Stability policy
    daily_completion_target = models.PositiveIntegerField(default=5)
    daily_focus_minutes_target = models.PositiveIntegerField(default=120)
    stability_streak_window_days = models.PositiveIntegerField(default=7)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Settings"
        verbose_name_plural = "App Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "AppSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return "LifeOS AppSettings"


class DomainCategory(models.Model):
    """User-extensible life domain lens (Tech, Academy, Home, …)."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#64748B")
    icon = models.CharField(max_length=50, default="folder")
    is_academy = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Domain categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """Cross-cutting label; optionally scoped to a domain."""

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#A1A1AA")
    domain = models.ForeignKey(
        DomainCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tags",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Certification(models.Model):
    """Professional credential target for Academy progress."""

    name = models.CharField(max_length=255)
    provider = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    credits_required = models.FloatField(default=0)
    credit_unit_type = models.CharField(max_length=32, default="CEU")

    def __str__(self) -> str:
        return f"{self.name} ({self.provider})" if self.provider else self.name


# ---------------------------------------------------------------------------
# Node / Leaf
# ---------------------------------------------------------------------------


class WorkspaceContainer(models.Model):
    """Structural hierarchy node (Epic, Course, List, Inbox, …)."""

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, help_text="Cmd+K #token match key")
    container_type = models.CharField(
        max_length=32,
        choices=SystemEnums.ContainerType.choices,
        default=SystemEnums.ContainerType.PROJECT,
    )
    para_state = models.CharField(
        max_length=20,
        choices=SystemEnums.PARACategory.choices,
        default=SystemEnums.PARACategory.PROJECT,
    )
    domain = models.ForeignKey(
        DomainCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="containers",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    priority = models.IntegerField(
        choices=SystemEnums.PriorityLevel.choices,
        default=SystemEnums.PriorityLevel.NORMAL,
    )
    urgency = models.CharField(
        max_length=20,
        choices=SystemEnums.UrgencyLevel.choices,
        default=SystemEnums.UrgencyLevel.NORMAL,
    )
    is_archived = models.BooleanField(default=False)
    external_url = models.URLField(blank=True, default="")
    provider = models.CharField(max_length=100, blank=True, default="")
    credit_unit_type = models.CharField(max_length=32, blank=True, default="")
    credits_earned = models.FloatField(default=0)
    certification = models.ForeignKey(
        Certification,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="containers",
    )
    order = models.PositiveIntegerField(default=0)
    extra_actual_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Manual time not attributable to a leaf (FR-FOCUS-002).",
    )
    notes = models.TextField(blank=True, default="")
    tags = models.ManyToManyField(Tag, blank=True, related_name="containers")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["container_type", "para_state"]),
        ]

    def clean(self):
        curr = self.parent
        seen = set()
        while curr is not None:
            if curr.pk == self.pk:
                raise ValidationError("Circular parenting dependency detected.")
            if curr.pk in seen:
                break
            seen.add(curr.pk)
            curr = curr.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "container"
            candidate = base
            n = 2
            while WorkspaceContainer.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{n}"
                n += 1
            self.slug = candidate
        self.is_archived = self.para_state == SystemEnums.PARACategory.ARCHIVE
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"[{self.get_container_type_display()}] {self.title}"


class ExecutionItem(models.Model):
    """Actionable leaf — tasks, learning work, life activities."""

    title = models.CharField(max_length=255)
    item_type = models.CharField(
        max_length=32,
        choices=SystemEnums.ItemType.choices,
        default=SystemEnums.ItemType.TASK,
    )
    status = models.CharField(
        max_length=20,
        choices=SystemEnums.ItemStatus.choices,
        default=SystemEnums.ItemStatus.INBOX,
    )
    priority = models.IntegerField(
        choices=SystemEnums.PriorityLevel.choices,
        default=SystemEnums.PriorityLevel.NORMAL,
    )
    urgency = models.CharField(
        max_length=20,
        choices=SystemEnums.UrgencyLevel.choices,
        default=SystemEnums.UrgencyLevel.NORMAL,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    fuzzy_timeframe = models.CharField(
        max_length=20,
        choices=SystemEnums.FuzzyTimeframe.choices,
        default=SystemEnums.FuzzyTimeframe.NONE,
    )
    estimated_minutes = models.PositiveIntegerField(default=30)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    extra_actual_seconds = models.PositiveIntegerField(default=0)
    parent_item = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subtasks",
    )
    stack_rank = models.PositiveIntegerField(default=0)
    external_url = models.URLField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_deleted = models.BooleanField(default=False)
    containers = models.ManyToManyField(
        WorkspaceContainer,
        through="ItemContainerLink",
        related_name="execution_items",
        blank=True,
    )
    depends_on = models.ManyToManyField(
        "self",
        through="ItemDependencyLink",
        symmetrical=False,
        related_name="dependents",
        blank=True,
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="execution_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stack_rank", "-priority", "due_at", "title"]
        indexes = [
            models.Index(fields=["status", "is_deleted"]),
            models.Index(fields=["due_at"]),
            models.Index(fields=["priority", "urgency"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def has_unmet_dependencies(self) -> bool:
        """True while any BLOCKS prerequisite is not COMPLETED."""
        return (
            ItemDependencyLink.objects.filter(
                from_item=self,
                link_type=SystemEnums.DependencyLinkType.BLOCKS,
                to_item__is_deleted=False,
            )
            .exclude(to_item__status=SystemEnums.ItemStatus.COMPLETED)
            .exists()
        )

    def primary_container(self) -> WorkspaceContainer | None:
        link = self.container_links.filter(is_primary=True).select_related("container").first()
        return link.container if link else None


class ItemContainerLink(models.Model):
    """Multi-home through table with exactly-one-primary rule for organized items."""

    item = models.ForeignKey(ExecutionItem, on_delete=models.CASCADE, related_name="container_links")
    container = models.ForeignKey(
        WorkspaceContainer, on_delete=models.CASCADE, related_name="item_links"
    )
    is_primary = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)

    class Meta:
        unique_together = ("item", "container")
        constraints = [
            models.UniqueConstraint(
                fields=["item"],
                condition=Q(is_primary=True),
                name="uniq_primary_container_per_item",
            )
        ]

    def __str__(self) -> str:
        flag = "primary" if self.is_primary else "home"
        return f"{self.item_id} → {self.container.slug} ({flag})"


class ItemDependencyLink(models.Model):
    """Leaf-to-leaf dependency; BLOCKS gates UI and scheduler."""

    from_item = models.ForeignKey(
        ExecutionItem, on_delete=models.CASCADE, related_name="dependency_links_out"
    )
    to_item = models.ForeignKey(
        ExecutionItem, on_delete=models.CASCADE, related_name="dependency_links_in"
    )
    link_type = models.CharField(
        max_length=20,
        choices=SystemEnums.DependencyLinkType.choices,
        default=SystemEnums.DependencyLinkType.BLOCKS,
    )

    class Meta:
        unique_together = ("from_item", "to_item", "link_type")

    def clean(self):
        if self.from_item_id and self.to_item_id and self.from_item_id == self.to_item_id:
            raise ValidationError("An item cannot depend on itself.")
        # Walk prerequisites for cycles when BLOCKS
        if self.link_type == SystemEnums.DependencyLinkType.BLOCKS and self.to_item_id:
            stack = [self.to_item_id]
            seen = set()
            while stack:
                current = stack.pop()
                if current == self.from_item_id:
                    raise ValidationError("Circular BLOCKS dependency detected.")
                if current in seen:
                    continue
                seen.add(current)
                nxt = ItemDependencyLink.objects.filter(
                    from_item_id=current,
                    link_type=SystemEnums.DependencyLinkType.BLOCKS,
                ).values_list("to_item_id", flat=True)
                stack.extend(nxt)

    def __str__(self) -> str:
        return f"{self.from_item_id} {self.link_type} {self.to_item_id}"


# ---------------------------------------------------------------------------
# Focus, schedule, calendar
# ---------------------------------------------------------------------------


class FocusSession(models.Model):
    """Server-authoritative focus timing history; at most one open session globally."""

    execution_item = models.ForeignKey(
        ExecutionItem, on_delete=models.CASCADE, related_name="focus_sessions"
    )
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    end_reason = models.CharField(
        max_length=20,
        choices=SystemEnums.FocusEndReason.choices,
        blank=True,
        default="",
    )

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["execution_item"],
                condition=Q(ended_at__isnull=True),
                name="uniq_open_focus_per_item",
            )
        ]

    def __str__(self) -> str:
        state = "open" if self.ended_at is None else "closed"
        return f"FocusSession({self.execution_item_id}, {state})"


class ScheduledAllocation(models.Model):
    """Persisted planner placement for an execution item."""

    execution_item = models.OneToOneField(
        ExecutionItem, on_delete=models.CASCADE, related_name="allocation"
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    score = models.FloatField(default=0)
    source = models.CharField(
        max_length=20,
        choices=SystemEnums.AllocationSource.choices,
        default=SystemEnums.AllocationSource.MANUAL,
    )
    external_event_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Google event id when pushed (P5-03).",
    )
    push_calendar = models.ForeignKey(
        "SyncedCalendar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pushed_allocations",
    )

    def __str__(self) -> str:
        return f"Allocation({self.execution_item_id} @ {self.start_at})"


class TimeAvailabilityBlock(models.Model):
    """Weekly availability window, optionally domain-scoped."""

    name = models.CharField(max_length=100)
    domain = models.ForeignKey(
        DomainCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="availability_blocks",
    )
    day_monday = models.BooleanField(default=True)
    day_tuesday = models.BooleanField(default=True)
    day_wednesday = models.BooleanField(default=True)
    day_thursday = models.BooleanField(default=True)
    day_friday = models.BooleanField(default=True)
    day_saturday = models.BooleanField(default=False)
    day_sunday = models.BooleanField(default=False)
    start_time = models.TimeField(default="09:00:00")
    end_time = models.TimeField(default="17:00:00")

    def __str__(self) -> str:
        return self.name


class CalendarIntegration(models.Model):
    """External calendar OAuth connection (Google or Microsoft Graph)."""

    provider = models.CharField(
        max_length=32,
        choices=SystemEnums.CalendarProvider.choices,
        default=SystemEnums.CalendarProvider.GOOGLE,
    )
    user_email = models.EmailField(blank=True, default="")
    credentials_json = models.JSONField(null=True, blank=True)
    sync_enabled = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_provider_display()} · {self.user_email or 'connected'}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "user_email"],
                condition=models.Q(user_email__gt=""),
                name="uniq_calendar_integration_provider_email",
            ),
        ]


class SyncedCalendar(models.Model):
    """A calendar discovered on a connected account; owner picks which to sync."""

    integration = models.ForeignKey(
        CalendarIntegration,
        on_delete=models.CASCADE,
        related_name="calendars",
    )
    calendar_id = models.CharField(max_length=255)
    summary = models.CharField(max_length=255)
    color = models.CharField(max_length=7, default="#8294AB")
    color_locked = models.BooleanField(
        default=False,
        help_text="When True, Refresh list keeps the owner-chosen color.",
    )
    is_primary = models.BooleanField(default=False)
    sync_enabled = models.BooleanField(default=False)
    display_enabled = models.BooleanField(
        default=True,
        help_text="Show events on the Planner calendar grid (independent of sync).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "summary"]
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "calendar_id"],
                name="uniq_synced_calendar_per_integration",
            ),
        ]

    def __str__(self) -> str:
        return self.summary or self.calendar_id


class CalendarEvent(models.Model):
    """Synced external calendar event used as busy/free for the solver."""

    integration = models.ForeignKey(
        CalendarIntegration,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
    )
    source_calendar = models.ForeignKey(
        SyncedCalendar,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
    )
    external_id = models.CharField(max_length=255, blank=True, default="")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    is_blocking = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["start_at", "end_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["source_calendar", "external_id"],
                condition=models.Q(source_calendar__isnull=False),
                name="uniq_calendar_event_per_source",
            ),
            models.UniqueConstraint(
                fields=["integration", "external_id"],
                condition=models.Q(source_calendar__isnull=True),
                name="uniq_calendar_event_legacy",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class RecurrenceRule(models.Model):
    """Recurrence pattern attached to an anchor execution item."""

    execution_item = models.OneToOneField(
        ExecutionItem, on_delete=models.CASCADE, related_name="recurrence"
    )
    rrule_text = models.CharField(max_length=255, blank=True, default="")
    freq = models.CharField(max_length=20, blank=True, default="")  # DAILY/WEEKLY/MONTHLY
    byweekday = models.CharField(max_length=64, blank=True, default="")  # e.g. MO,WE
    byhour = models.PositiveSmallIntegerField(null=True, blank=True)
    interval = models.PositiveIntegerField(default=1)
    next_occurrence_at = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional series start floor (BL-REC-001).",
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional series end (BL-REC-002); no spawn after this local day.",
    )
    active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.rrule_text or f"{self.freq}:{self.byweekday}"


# ---------------------------------------------------------------------------
# Notifications, stability, views, templates
# ---------------------------------------------------------------------------


class ReminderDispatch(models.Model):
    """Durable outbound reminder log — replaces any reminder_sent boolean."""

    execution_item = models.ForeignKey(
        ExecutionItem, on_delete=models.CASCADE, related_name="reminder_dispatches"
    )
    scheduled_allocation = models.ForeignKey(
        ScheduledAllocation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reminder_dispatches",
    )
    kind = models.CharField(max_length=32, choices=SystemEnums.ReminderKind.choices)
    fire_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    channel = models.CharField(max_length=64, default="webhook_ntfy")
    dedupe_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=20,
        choices=SystemEnums.ReminderDispatchStatus.choices,
        default=SystemEnums.ReminderDispatchStatus.PENDING,
    )
    snooze_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "fire_at"])]

    def __str__(self) -> str:
        return f"{self.kind}:{self.dedupe_key}"


class StabilitySnapshot(models.Model):
    """Daily System Stability Index rollup for Home Tier 3 / Analytics."""

    date = models.DateField(unique=True)
    completions_count = models.PositiveIntegerField(default=0)
    focus_seconds = models.PositiveIntegerField(default=0)
    planned_minutes = models.PositiveIntegerField(default=0)
    index_score = models.PositiveSmallIntegerField(default=0)
    band = models.CharField(
        max_length=20,
        choices=SystemEnums.StabilityBand.choices,
        default=SystemEnums.StabilityBand.STABLE,
    )
    streak_days = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date} {self.band} ({self.index_score})"


class SavedView(models.Model):
    """Named facet/query preset for Matrix, Overview, or Board."""

    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    target_surface = models.CharField(
        max_length=20,
        choices=SystemEnums.SavedViewSurface.choices,
        default=SystemEnums.SavedViewSurface.MATRIX,
    )
    query_params = models.JSONField(default=dict, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class WorkspaceTemplate(models.Model):
    """Curated cloneable Node/Leaf skeleton (not a marketplace)."""

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    domain_hint = models.ForeignKey(
        DomainCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="templates",
    )
    para_hint = models.CharField(
        max_length=20,
        choices=SystemEnums.PARACategory.choices,
        blank=True,
        default="",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.title


class WorkspaceTemplateNode(models.Model):
    """Template tree row describing containers and/or starter leaves to clone."""

    template = models.ForeignKey(
        WorkspaceTemplate, on_delete=models.CASCADE, related_name="nodes"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    title = models.CharField(max_length=255)
    node_kind = models.CharField(
        max_length=20,
        choices=[("container", "Container"), ("item", "Item")],
        default="container",
    )
    container_type = models.CharField(
        max_length=32,
        choices=SystemEnums.ContainerType.choices,
        blank=True,
        default="",
    )
    item_type = models.CharField(
        max_length=32,
        choices=SystemEnums.ItemType.choices,
        blank=True,
        default="",
    )
    estimated_minutes = models.PositiveIntegerField(default=30)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.template.slug}:{self.title}"

# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/models.py
# Description: Models definitions for WorkspaceContainer, ExecutionItem, and AppSettings
# Component: Core / Database Models
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
# ==============================================================================
"""Database model definitions for the LifeOS Django application.

Contains the unified DRY models: WorkspaceContainer (for hierarchical structure)
and ExecutionItem (for actionable items), along with system preferences (AppSettings).
"""

from django.db import models
from django.db.models import Sum
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

class DomainCategory(models.Model):
    """
    Dynamic life domain categories customizable by the user (FR-SET-007 / FR-SET-008).
    Can be flagged as 'is_academy' to toggle academic-specific dashboard analytics views.
    """
    name = models.CharField(max_length=100, unique=True)
    is_academy = models.BooleanField(default=False)
    color = models.CharField(max_length=7, default='#9966CC') # Hex color (e.g. #50C878)
    icon = models.CharField(max_length=50, default='folder') # Icon identifier

    def __str__(self):
        return self.name


class AppSettings(models.Model):
    """
    Singleton model for system-wide user preferences.
    Always access via AppSettings.get_solo()
    """
    pomodoro_duration = models.IntegerField(default=25)
    start_of_work_day = models.TimeField(default="09:00:00")
    enable_ai_scheduling = models.BooleanField(default=True)
    
    # V3.0 Location & Unit Configurations
    location_name = models.CharField(max_length=255, default='Seattle, WA')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    auto_detect_location = models.BooleanField(default=False)
    use_imperial = models.BooleanField(default=False) # Metric vs Imperial
    use_24h_time = models.BooleanField(default=False) # 12h vs 24h
    timezone = models.CharField(max_length=100, default='UTC')
    dashboard_card_names = models.JSONField(default=dict, blank=True) # User custom labels for dashboard cards

    # V4.0 SLM Scheduler Settings
    priority_weight = models.FloatField(default=1.5)
    urgency_weight = models.FloatField(default=2.0)
    slm_provider = models.CharField(
        max_length=50,
        choices=[
            ('Local Ollama', 'Local Ollama'),
            ('Cloud API', 'Cloud API'),
            ('Download Llama-cpp', 'Download Llama-cpp'),
            ('Skip', 'Skip')
        ],
        default='Local Ollama'
    )
    slm_endpoint = models.CharField(max_length=255, default='http://localhost:11434/api/generate')

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "System AppSettings"


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#9966CC", help_text="Hex color code")
    
    def __str__(self):
        return self.name


class WorkspaceContainer(models.Model):
    """
    Unified type-discriminated container supporting hierarchical structures:
    Epics, Projects, Specializations, Courses, and Modules.
    """
    CONTAINER_TYPES = [
        ('Epic', 'Epic'),
        ('Project', 'Project'),
        ('Specialization', 'Specialization'),
        ('Course', 'Course'),
        ('Module', 'Module'),
    ]

    PARA_CATEGORIES = [
        ('Projects', 'Projects'),
        ('Areas', 'Areas'),
        ('Resources', 'Resources'),
        ('Archives', 'Archives'),
    ]

    title = models.CharField(max_length=255)
    container_type = models.CharField(max_length=50, choices=CONTAINER_TYPES)
    
    parent = models.ForeignKey(
        'self', null=True, blank=True, 
        on_delete=models.CASCADE, related_name='children'
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Category markers (FR-DATA-004)
    domain = models.ForeignKey(
        DomainCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='containers'
    )
    para_category = models.CharField(
        max_length=100, choices=PARA_CATEGORIES, null=True, blank=True, db_index=True
    )
    
    # Archival state (FR-LIFE-001)
    is_archived = models.BooleanField(default=False, db_index=True)
    
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]

    URGENCY_CHOICES = [
        ('Low', 'Low'),
        ('Normal', 'Normal'),
        ('High', 'High'),
        ('Immediate', 'Immediate'),
    ]

    # V5 Extensions
    tags = models.ManyToManyField(Tag, blank=True, related_name='containers')
    priority = models.CharField(max_length=50, choices=PRIORITY_CHOICES, default='Medium', db_index=True)
    urgency = models.CharField(max_length=50, choices=URGENCY_CHOICES, default='Normal', db_index=True)

    def clean(self):
        # Prevent self-referencing hierarchy cycles (FR-DATA-001.3)
        if self.parent == self:
            raise ValidationError("A container cannot be its own parent.")
        
        # Prevent deeper cycles
        curr = self.parent
        while curr is not None:
            if curr == self:
                raise ValidationError("Circular relationship detected in container hierarchy.")
            curr = curr.parent

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_total_time_spent_seconds(self):
        total = 0
        # 1. Add time of child containers
        for child in self.children.filter(is_archived=False):
            total += child.get_total_time_spent_seconds()
        # 2. Add time of child tasks directly parented to this container
        container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
        items = ExecutionItem.objects.filter(content_type=container_ct, object_id=self.id, is_deleted=False)
        
        # Optimization: Aggregate direct time
        direct_sum = items.aggregate(Sum('time_spent_seconds'))['time_spent_seconds__sum'] or 0
        total += direct_sum
        
        # Add subtask recursive time (excluding direct time since we just added it)
        for item in items:
            total += (item.get_total_time_spent_seconds() - item.time_spent_seconds)
        return total

    @property
    def total_time_duration_str(self):
        return format_seconds_to_duration(self.get_total_time_spent_seconds())

    def __str__(self):
        return f"{self.container_type}: {self.title}"


class ExecutionItem(models.Model):
    """
    Unified actionable leaf-node model representing Tasks, Subtasks,
    LearningTasks, and LifeActivities.
    """
    ITEM_TYPES = [
        ('Task', 'Task'),
        ('LearningTask', 'LearningTask'),
        ('LifeActivity', 'LifeActivity'),
    ]

    PARA_CATEGORIES = [
        ('Projects', 'Projects'),
        ('Areas', 'Areas'),
        ('Resources', 'Resources'),
        ('Archives', 'Archives'),
    ]

    STATUS_CHOICES = [
        ('Inbox', 'Inbox'),
        ('Backlog', 'Backlog'),
        ('Planned', 'Planned'),
        ('In Progress', 'In Progress'),
        ('Blocked', 'Blocked'),
        ('Completed', 'Completed'),
    ]

    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]

    URGENCY_CHOICES = [
        ('Low', 'Low'),
        ('Normal', 'Normal'),
        ('High', 'High'),
        ('Immediate', 'Immediate'),
    ]

    title = models.CharField(max_length=255)
    item_type = models.CharField(max_length=50, choices=ITEM_TYPES)
    is_completed = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Generic relation to link to either WorkspaceContainer or another ExecutionItem
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    # Focus Engine metrics (FR-FOCUS-001)
    duration_estimate = models.PositiveIntegerField(help_text="Minutes", default=30)
    time_spent_seconds = models.PositiveIntegerField(default=0, help_text="Seconds elapsed")
    is_active = models.BooleanField(default=False, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)

    # Category markers (FR-DATA-004)
    domain = models.ForeignKey(
        DomainCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='items'
    )
    para_category = models.CharField(
        max_length=100, choices=PARA_CATEGORIES, null=True, blank=True, db_index=True
    )

    # V2.0 Lifecycle status, priority, and pins
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Inbox', db_index=True)
    priority = models.CharField(max_length=50, choices=PRIORITY_CHOICES, default='Medium', db_index=True)
    urgency = models.CharField(max_length=50, choices=URGENCY_CHOICES, default='Normal', db_index=True)
    is_pinned = models.BooleanField(default=False, db_index=True)
    
    # V5 Extensions
    tags = models.ManyToManyField(Tag, blank=True, related_name='execution_items')

    # V3.0 Timeframes & Calendaring Dates
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    fuzzy_timeframe = models.CharField(
        max_length=50, 
        choices=[
            ('Today', 'Today'), 
            ('Tomorrow', 'Tomorrow'), 
            ('Weekend', 'Coming Weekend'), 
            ('Week', 'This Week'), 
            ('Month', 'This Month')
        ], 
        null=True, blank=True
    )
    extra_actual_seconds = models.PositiveIntegerField(default=0)

    # Archival & Soft delete states (FR-LIFE-001, FR-LIFE-002)
    is_archived = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def save(self, *args, **kwargs):
        # Detect if completion changed to True
        is_new_completion = False
        if self.pk:
            old_self = ExecutionItem.objects.filter(pk=self.pk).first()
            if old_self:
                if not old_self.is_completed and (self.status == 'Completed' or self.is_completed):
                    is_new_completion = True
                
                # FUNC-5: Sync when un-completing
                if old_self.status == 'Completed' and self.status != 'Completed':
                    self.is_completed = False
                elif old_self.is_completed and not self.is_completed:
                    if self.status == 'Completed':
                        self.status = 'Planned'
        
        # Sync completion flags (FR-LIFECYCLE-001)
        if self.status == 'Completed':
            self.is_completed = True
        elif self.is_completed:
            self.status = 'Completed'
        
        # SPEC-6 & FUNC-4: Default to Backlog if no dates when triaged
        if (self.content_type is not None or self.object_id is not None) and self.status == 'Inbox':
            if self.start_date or self.due_date:
                self.status = 'Planned'
            else:
                self.status = 'Backlog'

        super().save(*args, **kwargs)
        
        # Trigger recurrence cloning
        if is_new_completion:
            self.trigger_recurrence()

    def trigger_recurrence(self):
        recur = getattr(self, 'recurrence', None)
        if not recur:
            return
            
        from django.utils import timezone
        import datetime
        
        delta = None
        freq = recur.frequency
        if freq == 'Daily':
            delta = datetime.timedelta(days=1)
        elif freq == 'Weekly':
            delta = datetime.timedelta(weeks=1)
        elif freq == 'Monthly':
            delta = datetime.timedelta(days=30)
        elif freq == 'Quarterly':
            delta = datetime.timedelta(days=90)
        elif freq == 'Annually':
            delta = datetime.timedelta(days=365)
        elif freq == 'Custom':
            days = 7
            if recur.custom_period == 'month':
                days = 30
            elif recur.custom_period == 'year':
                days = 365
            count = recur.custom_times_count or 1
            delta = datetime.timedelta(days=max(1, days // count))
            
        new_start = None
        new_due = None
        
        if self.start_date and delta:
            new_start = self.start_date + delta
        if self.due_date and delta:
            new_due = self.due_date + delta
        elif delta:
            new_due = timezone.now() + delta
            
        new_item = ExecutionItem.objects.create(
            title=self.title,
            item_type=self.item_type,
            status='Planned',
            is_completed=False,
            content_type=self.content_type,
            object_id=self.object_id,
            duration_estimate=self.duration_estimate,
            domain=self.domain,
            para_category=self.para_category,
            priority=self.priority,
            start_date=new_start,
            due_date=new_due,
            fuzzy_timeframe=self.fuzzy_timeframe,
        )
        
        RecurringConfig.objects.create(
            execution_item=new_item,
            frequency=recur.frequency,
            custom_times_count=recur.custom_times_count,
            custom_period=recur.custom_period
        )

    def get_total_time_spent_seconds(self):
        total = self.time_spent_seconds + self.extra_actual_seconds
        item_ct = ContentType.objects.get_for_model(ExecutionItem)
        subitems = ExecutionItem.objects.filter(content_type=item_ct, object_id=self.id, is_deleted=False)
        
        # Optimization: Aggregate direct time
        direct_sum = subitems.aggregate(Sum('time_spent_seconds'))['time_spent_seconds__sum'] or 0
        total += direct_sum
        
        # Add sub-subtask recursive time
        for sub in subitems:
            total += (sub.get_total_time_spent_seconds() - sub.time_spent_seconds)
        return total

    @property
    def total_time_duration_str(self):
        return format_seconds_to_duration(self.get_total_time_spent_seconds())

    def __str__(self):
        return f"{self.item_type}: {self.title}"


class Certification(models.Model):
    """
    Tracks certification state, renewals, and PDU/SEU progress (Section 3.2).
    """
    title = models.CharField(max_length=255)
    achieved_date = models.DateField(null=True, blank=True)
    renewal_date = models.DateField(null=True, blank=True)
    pdus_required = models.PositiveIntegerField(default=0)
    pdus_earned = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title


class RecurringConfig(models.Model):
    """
    Engine schema for recurrent execution items (FR-GEN-005).
    """
    execution_item = models.OneToOneField(
        ExecutionItem, on_delete=models.CASCADE, related_name='recurrence'
    )
    frequency = models.CharField(
        max_length=50, 
        choices=[
            ('Daily', 'Daily'),
            ('Weekly', 'Weekly'),
            ('Monthly', 'Monthly'),
            ('Quarterly', 'Quarterly'),
            ('Annually', 'Annually'),
            ('Custom', 'Custom'),
        ]
    )
    custom_times_count = models.PositiveIntegerField(null=True, blank=True)
    custom_period = models.CharField(max_length=50, null=True, blank=True) # 'week', 'month', 'year'

    def __str__(self):
        return f"{self.frequency} Recurrence for {self.execution_item.title}"


class GoogleCalendar(models.Model):
    """
    Integrates external Google Calendar sync schedules.
    """
    calendar_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255, default='Primary')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class NotionIntegration(models.Model):
    """
    Integrates Notion workspace document links (FR-INT-002).
    """
    notion_page_url = models.URLField(max_length=1000, null=True, blank=True)
    notion_token = models.CharField(max_length=500, null=True, blank=True)
    execution_item = models.OneToOneField(
        ExecutionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='notion_link'
    )
    container = models.OneToOneField(
        WorkspaceContainer, on_delete=models.SET_NULL, null=True, blank=True, related_name='notion_link'
    )

    def __str__(self):
        return f"Notion integration for {self.execution_item.title if self.execution_item else self.container.title if self.container else 'Unknown'}"
        
    def clean(self):
        super().clean()
        if (self.execution_item and self.container) or (not self.execution_item and not self.container):
            from django.core.exceptions import ValidationError
            raise ValidationError("NotionIntegration must link to exactly one ExecutionItem or WorkspaceContainer.")


# Utility helpers for human-readable duration strings
def parse_duration_to_seconds(s):
    """
    Converts duration strings like '1y 2mo 3w 5d 4h 30m' into total seconds.
    Falls back to treating pure digit values as minutes (V1/V2 compatibility).
    """
    import re
    if not s:
        return 0
    s = str(s).strip().lower()
    if s.isdigit():
        return int(s) * 60

    pattern = re.compile(r'(\d+)\s*([a-z]+)')
    total_seconds = 0
    units = {
        'y': 365 * 24 * 3600,
        'year': 365 * 24 * 3600,
        'years': 365 * 24 * 3600,
        'mo': 30 * 24 * 3600,
        'month': 30 * 24 * 3600,
        'months': 30 * 24 * 3600,
        'w': 7 * 24 * 3600,
        'week': 7 * 24 * 3600,
        'weeks': 7 * 24 * 3600,
        'd': 24 * 3600,
        'day': 24 * 3600,
        'days': 24 * 3600,
        'h': 3600,
        'hour': 3600,
        'hours': 3600,
        'm': 60,
        'min': 60,
        'mins': 60,
        'minute': 60,
        'minutes': 60,
        's': 1,
        'sec': 1,
        'secs': 1,
    }
    matches = pattern.findall(s)
    for val, unit in matches:
        if unit in units:
            total_seconds += int(val) * units[unit]
    return total_seconds


def format_seconds_to_duration(seconds):
    """
    Converts raw seconds into readable '1y 2mo 3w 5d 4h 30m 15s' format.
    """
    if not seconds:
        return "0m"
    units = [
        ('y', 365 * 24 * 3600),
        ('mo', 30 * 24 * 3600),
        ('w', 7 * 24 * 3600),
        ('d', 24 * 3600),
        ('h', 3600),
        ('m', 60),
    ]
    parts = []
    rem = seconds
    for label, count in units:
        val = rem // count
        if val > 0:
            parts.append(f"{val}{label}")
            rem = rem % count
    if rem > 0:
        parts.append(f"{rem}s")
    return " ".join(parts) if parts else "0m"


# ==============================================================================
# V4.0 SLM-Powered Scheduling Engine Models
# ==============================================================================

class GoogleCalendarEvent(models.Model):
    calendar = models.ForeignKey('GoogleCalendar', on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_blocking = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.title} ({self.start_time} - {self.end_time})"


class TimeAvailabilityBlock(models.Model):
    name = models.CharField(max_length=255)
    domain = models.ForeignKey(DomainCategory, on_delete=models.SET_NULL, null=True, blank=True)
    
    day_monday = models.BooleanField(default=True)
    day_tuesday = models.BooleanField(default=True)
    day_wednesday = models.BooleanField(default=True)
    day_thursday = models.BooleanField(default=True)
    day_friday = models.BooleanField(default=True)
    day_saturday = models.BooleanField(default=False)
    day_sunday = models.BooleanField(default=False)
    
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} [{self.start_time} - {self.end_time}]"


class ScheduledTaskAllocation(models.Model):
    execution_item = models.OneToOneField(ExecutionItem, on_delete=models.CASCADE, related_name='scheduled_allocation')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    score_metric = models.FloatField(default=0.0)

    def __str__(self):
        return f"Allocated: {self.execution_item.title} at {self.start_time}"

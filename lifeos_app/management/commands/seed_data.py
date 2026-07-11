# ==============================================================================
# File: lifeos_app/management/commands/seed_data.py
# Description: Comprehensive deterministic seed dataset for LifeOS V2 testing
# Component: Core / Database Seeding
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Seed LifeOS V2 with rich data for automated and manual cockpit testing.

Covers domains, tags, system lists, nested containers, multi-homing, inbox
orphans, focus sessions, allocations, availability, dependencies, academy,
saved views, templates, reminders, and stability snapshots.

Usage:
  python manage.py seed_data
  python manage.py seed_data --flush
  python manage.py seed_data --flush --username owner --password changeme
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    CalendarEvent,
    CalendarIntegration,
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
    SystemEnums,
    Tag,
    TimeAvailabilityBlock,
    WorkspaceContainer,
    WorkspaceTemplate,
    WorkspaceTemplateNode,
)


class Command(BaseCommand):
    help = "Seed a comprehensive LifeOS V2 dataset for automated and manual testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing app data before seeding (keeps auth users unless --username given).",
        )
        parser.add_argument("--username", default="", help="Ensure owner superuser with this username.")
        parser.add_argument("--password", default="", help="Password for --username (required with --username).")
        parser.add_argument("--email", default="owner@lifeos.local", help="Owner email.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()
            self.stdout.write(self.style.WARNING("Flushed app tables."))

        if options["username"]:
            if not options["password"]:
                self.stderr.write(self.style.ERROR("--password is required with --username"))
                return
            self._ensure_owner(options["username"], options["password"], options["email"])

        self._seed()
        self.stdout.write(self.style.SUCCESS("seed_data complete."))

    def _flush(self):
        """Wipe V2 app tables in dependency-safe order (tolerates missing relations)."""
        from django.db import ProgrammingError

        for model in (
            ReminderDispatch,
            FocusSession,
            ScheduledAllocation,
            RecurrenceRule,
            ItemDependencyLink,
            ItemContainerLink,
            CalendarEvent,
            CalendarIntegration,
            ExecutionItem,
            WorkspaceTemplateNode,
            WorkspaceTemplate,
            WorkspaceContainer,
            SavedView,
            StabilitySnapshot,
            TimeAvailabilityBlock,
            Tag,
            Certification,
            DomainCategory,
            AppSettings,
        ):
            try:
                model.objects.all().delete()
            except ProgrammingError:
                # Table not created yet (partial migrate) — skip
                continue

    def _ensure_owner(self, username: str, password: str, email: str):
        from django.core.exceptions import ValidationError

        from lifeos_app.services.owner import create_owner_user

        try:
            user, created = create_owner_user(username, password, email, force=True)
        except ValidationError as exc:
            self.stderr.write(self.style.ERROR(str(exc.messages[0] if exc.messages else exc)))
            return
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} owner superuser '{user.username}'."))

    def _seed(self):
        now = timezone.now()
        today = timezone.localdate()

        settings = AppSettings.get_solo()
        settings.timezone = "America/Phoenix"
        settings.location_name = "Phoenix, AZ"
        settings.latitude = 33.66
        settings.longitude = -112.34
        settings.use_imperial = True
        settings.daily_completion_target = 5
        settings.daily_focus_minutes_target = 120
        settings.notifications_enabled = False
        settings.reminder_lead_minutes = 15
        settings.save()

        # Domains
        domains = {}
        for name, slug, color, icon, academy in [
            ("Tech", "tech", "#8B9EF5", "terminal", False),
            ("Theater", "theater", "#B794F6", "sparkles", False),
            ("Academy", "academy", "#4EDFD4", "academic-cap", True),
            ("Home", "home", "#5EEAB8", "home", False),
            ("Governance", "governance", "#9B82E8", "shield", False),
        ]:
            domains[slug], _ = DomainCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "color": color,
                    "icon": icon,
                    "is_academy": academy,
                    "is_active": True,
                },
            )

        # Tags
        tags = {}
        for name, color, domain_slug in [
            ("deep-work", "#5EEAB8", "tech"),
            ("quick-win", "#FACC15", None),
            ("blocked-ext", "#F87171", None),
            ("lab", "#4EDFD4", "academy"),
            ("rehearsal", "#B794F6", "theater"),
            ("errand", "#5EEAB8", "home"),
            ("compliance", "#9B82E8", "governance"),
        ]:
            tags[name], _ = Tag.objects.update_or_create(
                name=name,
                defaults={
                    "color": color,
                    "domain": domains[domain_slug] if domain_slug else None,
                },
            )

        cert, _ = Certification.objects.update_or_create(
            name="CompTIA Security+",
            defaults={
                "provider": "CompTIA",
                "description": "Foundational cybersecurity certification.",
                "credits_required": 40,
                "credit_unit_type": "CEU",
            },
        )

        # System lists
        inbox, _ = WorkspaceContainer.objects.update_or_create(
            slug="inbox",
            defaults={
                "title": "Inbox",
                "container_type": SystemEnums.ContainerType.INBOX,
                "para_state": SystemEnums.PARACategory.AREA,
                "domain": None,
            },
        )
        today_list, _ = WorkspaceContainer.objects.update_or_create(
            slug="today",
            defaults={
                "title": "Today",
                "container_type": SystemEnums.ContainerType.LIST,
                "para_state": SystemEnums.PARACategory.AREA,
                "domain": None,
            },
        )
        this_week, _ = WorkspaceContainer.objects.update_or_create(
            slug="this-week",
            defaults={
                "title": "This Week",
                "container_type": SystemEnums.ContainerType.LIST,
                "para_state": SystemEnums.PARACategory.AREA,
                "domain": None,
            },
        )

        # Tech hierarchy
        epic, _ = WorkspaceContainer.objects.update_or_create(
            slug="lifeos-v2",
            defaults={
                "title": "LifeOS V2 Rewrite",
                "container_type": SystemEnums.ContainerType.EPIC,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["tech"],
                "priority": SystemEnums.PriorityLevel.CRITICAL,
                "urgency": SystemEnums.UrgencyLevel.HIGH,
            },
        )
        epic.tags.set([tags["deep-work"]])

        sprint, _ = WorkspaceContainer.objects.update_or_create(
            slug="p0-foundation",
            defaults={
                "title": "P0 Foundation Sprint",
                "container_type": SystemEnums.ContainerType.SPRINT,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["tech"],
                "parent": epic,
                "priority": SystemEnums.PriorityLevel.HIGH,
            },
        )

        infra, _ = WorkspaceContainer.objects.update_or_create(
            slug="infrastructure",
            defaults={
                "title": "Home Lab Infrastructure",
                "container_type": SystemEnums.ContainerType.PROJECT,
                "para_state": SystemEnums.PARACategory.AREA,
                "domain": domains["tech"],
                "priority": SystemEnums.PriorityLevel.HIGH,
            },
        )

        # Academy hierarchy
        specialization, _ = WorkspaceContainer.objects.update_or_create(
            slug="cybersec-track",
            defaults={
                "title": "Cybersecurity Specialization",
                "container_type": SystemEnums.ContainerType.SPECIALIZATION,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["academy"],
                "certification": cert,
                "provider": "Coursera",
                "credit_unit_type": "CEU",
                "credits_earned": 12,
            },
        )
        course, _ = WorkspaceContainer.objects.update_or_create(
            slug="secplus-course",
            defaults={
                "title": "Security+ Prep Course",
                "container_type": SystemEnums.ContainerType.COURSE,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["academy"],
                "parent": specialization,
                "certification": cert,
                "provider": "Udemy",
                "credits_earned": 8,
            },
        )
        module, _ = WorkspaceContainer.objects.update_or_create(
            slug="crypto-module",
            defaults={
                "title": "Cryptography Module",
                "container_type": SystemEnums.ContainerType.MODULE,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["academy"],
                "parent": course,
                "certification": cert,
                "credits_earned": 2,
            },
        )

        # Theater + Home + Governance
        show, _ = WorkspaceContainer.objects.update_or_create(
            slug="spring-showcase",
            defaults={
                "title": "Spring Showcase",
                "container_type": SystemEnums.ContainerType.PROJECT,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["theater"],
            },
        )
        home_ops, _ = WorkspaceContainer.objects.update_or_create(
            slug="home-ops",
            defaults={
                "title": "Home Operations",
                "container_type": SystemEnums.ContainerType.PROJECT,
                "para_state": SystemEnums.PARACategory.AREA,
                "domain": domains["home"],
            },
        )
        compliance, _ = WorkspaceContainer.objects.update_or_create(
            slug="annual-compliance",
            defaults={
                "title": "Annual Compliance Pack",
                "container_type": SystemEnums.ContainerType.PROJECT,
                "para_state": SystemEnums.PARACategory.PROJECT,
                "domain": domains["governance"],
            },
        )
        archived, _ = WorkspaceContainer.objects.update_or_create(
            slug="old-blog",
            defaults={
                "title": "Retired Blog Migration",
                "container_type": SystemEnums.ContainerType.PROJECT,
                "para_state": SystemEnums.PARACategory.ARCHIVE,
                "domain": domains["tech"],
            },
        )

        def link(item, container, primary=False, pinned=False):
            ItemContainerLink.objects.update_or_create(
                item=item,
                container=container,
                defaults={"is_primary": primary, "pinned": pinned},
            )

        def make_item(slug_key, title, **kwargs):
            """Idempotent item create keyed by title for seed re-runs."""
            defaults = {
                "item_type": SystemEnums.ItemType.TASK,
                "status": SystemEnums.ItemStatus.BACKLOG,
                "priority": SystemEnums.PriorityLevel.NORMAL,
                "urgency": SystemEnums.UrgencyLevel.NORMAL,
                "estimated_minutes": 30,
            }
            defaults.update(kwargs)
            item, _ = ExecutionItem.objects.update_or_create(title=title, defaults=defaults)
            return item

        # Inbox orphans (triage scenarios)
        orphan_a = make_item(
            "orphan-a",
            "Brain dump: check WireGuard handshake logs",
            status=SystemEnums.ItemStatus.INBOX,
            priority=SystemEnums.PriorityLevel.HIGH,
        )
        orphan_b = make_item(
            "orphan-b",
            "Random idea: ambient dock badges",
            status=SystemEnums.ItemStatus.INBOX,
            priority=SystemEnums.PriorityLevel.LOW,
        )

        # Tech sprint work
        schema_item = make_item(
            "schema",
            "Implement V2 Node/Leaf schema",
            status=SystemEnums.ItemStatus.COMPLETED,
            priority=SystemEnums.PriorityLevel.CRITICAL,
            estimated_minutes=120,
            time_spent_seconds=5400,
        )
        link(schema_item, sprint, primary=True)
        schema_item.tags.set([tags["deep-work"]])

        shell_item = make_item(
            "shell",
            "Build cockpit shell + Home bento",
            status=SystemEnums.ItemStatus.IN_PROGRESS,
            priority=SystemEnums.PriorityLevel.CRITICAL,
            urgency=SystemEnums.UrgencyLevel.IMMEDIATE,
            estimated_minutes=90,
            due_at=now + timedelta(hours=4),
        )
        link(shell_item, sprint, primary=True)
        link(shell_item, today_list, primary=False, pinned=True)
        shell_item.tags.set([tags["deep-work"]])

        seed_item = make_item(
            "seed",
            "Write comprehensive seed_data command",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
            estimated_minutes=60,
            due_at=now + timedelta(hours=6),
        )
        link(seed_item, sprint, primary=True)
        link(seed_item, today_list, primary=False)

        capture_item = make_item(
            "capture",
            "Wire Cmd+K Lightning Capture",
            status=SystemEnums.ItemStatus.BACKLOG,
            priority=SystemEnums.PriorityLevel.HIGH,
            estimated_minutes=90,
            fuzzy_timeframe=SystemEnums.FuzzyTimeframe.THIS_WEEK,
        )
        link(capture_item, epic, primary=True)
        link(capture_item, this_week, primary=False)

        # Dependency chain: focus engine blocked by shell
        focus_item = make_item(
            "focus-engine",
            "Implement Focus Engine start/pause/complete",
            status=SystemEnums.ItemStatus.BACKLOG,
            priority=SystemEnums.PriorityLevel.HIGH,
            estimated_minutes=75,
        )
        link(focus_item, epic, primary=True)
        ItemDependencyLink.objects.update_or_create(
            from_item=focus_item,
            to_item=shell_item,
            link_type=SystemEnums.DependencyLinkType.BLOCKS,
        )

        # Infra + multi-home
        wg_item = make_item(
            "wg",
            "Fix pfSense WireGuard handshake timeout",
            status=SystemEnums.ItemStatus.BLOCKED,
            priority=SystemEnums.PriorityLevel.CRITICAL,
            urgency=SystemEnums.UrgencyLevel.HIGH,
            estimated_minutes=45,
            due_at=now + timedelta(days=1),
        )
        link(wg_item, infra, primary=True)
        link(wg_item, today_list, primary=False)
        wg_item.tags.set([tags["blocked-ext"], tags["deep-work"]])

        # Academy learning tasks
        lab_item = make_item(
            "lab",
            "Complete cryptography practice lab",
            item_type=SystemEnums.ItemType.LEARNING_TASK,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.NORMAL,
            estimated_minutes=50,
            due_at=now + timedelta(days=2),
        )
        link(lab_item, module, primary=True)
        lab_item.tags.set([tags["lab"]])

        quiz_item = make_item(
            "quiz",
            "Security+ practice quiz set B",
            item_type=SystemEnums.ItemType.LEARNING_TASK,
            status=SystemEnums.ItemStatus.BACKLOG,
            estimated_minutes=40,
        )
        link(quiz_item, course, primary=True)
        ItemDependencyLink.objects.update_or_create(
            from_item=quiz_item,
            to_item=lab_item,
            link_type=SystemEnums.DependencyLinkType.BLOCKS,
        )

        # Theater / home / governance
        cue_item = make_item(
            "cues",
            "Mark lighting cues for Act II",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.NORMAL,
            estimated_minutes=35,
            due_at=now + timedelta(days=3),
        )
        link(cue_item, show, primary=True)
        cue_item.tags.set([tags["rehearsal"]])

        grocery = make_item(
            "grocery",
            "Restock pantry staples",
            item_type=SystemEnums.ItemType.LIFE_ACTIVITY,
            status=SystemEnums.ItemStatus.BACKLOG,
            priority=SystemEnums.PriorityLevel.LOW,
            estimated_minutes=40,
            fuzzy_timeframe=SystemEnums.FuzzyTimeframe.WEEKEND,
        )
        link(grocery, home_ops, primary=True)
        grocery.tags.set([tags["errand"], tags["quick-win"]])

        tax_item = make_item(
            "tax-docs",
            "Assemble annual compliance document pack",
            status=SystemEnums.ItemStatus.BACKLOG,
            priority=SystemEnums.PriorityLevel.HIGH,
            estimated_minutes=120,
            due_at=now + timedelta(days=14),
        )
        link(tax_item, compliance, primary=True)
        tax_item.tags.set([tags["compliance"]])

        # Soft-deleted + archived-primary scenarios
        deleted = make_item(
            "deleted",
            "Obsolete spike notes (soft-deleted)",
            status=SystemEnums.ItemStatus.BACKLOG,
            is_deleted=True,
        )
        link(deleted, sprint, primary=True)

        archived_item = make_item(
            "archived-task",
            "Export old blog posts",
            status=SystemEnums.ItemStatus.COMPLETED,
            time_spent_seconds=1800,
        )
        link(archived_item, archived, primary=True)

        # Subtask under shell
        sub = make_item(
            "sub-accent",
            "Define status accent CSS tokens",
            item_type=SystemEnums.ItemType.SUBTASK,
            status=SystemEnums.ItemStatus.BACKLOG,
            parent_item=shell_item,
            estimated_minutes=25,
        )
        link(sub, sprint, primary=True)

        # Focus sessions — one open on shell, one closed history
        FocusSession.objects.filter(ended_at__isnull=True).delete()
        FocusSession.objects.create(
            execution_item=shell_item,
            started_at=now - timedelta(minutes=18),
            ended_at=None,
        )
        FocusSession.objects.create(
            execution_item=schema_item,
            started_at=now - timedelta(hours=5),
            ended_at=now - timedelta(hours=3, minutes=30),
            duration_seconds=5400,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )

        # Allocations for horizon / planner tests
        ScheduledAllocation.objects.update_or_create(
            execution_item=seed_item,
            defaults={
                "start_at": now + timedelta(hours=2),
                "end_at": now + timedelta(hours=3),
                "score": 12.5,
                "source": SystemEnums.AllocationSource.SOLVER,
            },
        )
        ScheduledAllocation.objects.update_or_create(
            execution_item=lab_item,
            defaults={
                "start_at": now + timedelta(days=1, hours=10),
                "end_at": now + timedelta(days=1, hours=11),
                "score": 8.0,
                "source": SystemEnums.AllocationSource.MANUAL,
            },
        )

        # Availability
        TimeAvailabilityBlock.objects.update_or_create(
            name="Weekday Deep Work",
            defaults={
                "domain": domains["tech"],
                "day_monday": True,
                "day_tuesday": True,
                "day_wednesday": True,
                "day_thursday": True,
                "day_friday": True,
                "day_saturday": False,
                "day_sunday": False,
                "start_time": "09:00:00",
                "end_time": "12:00:00",
            },
        )
        TimeAvailabilityBlock.objects.update_or_create(
            name="Evening Academy",
            defaults={
                "domain": domains["academy"],
                "day_monday": True,
                "day_wednesday": True,
                "day_friday": True,
                "start_time": "19:00:00",
                "end_time": "21:00:00",
            },
        )

        # Calendar
        integration, _ = CalendarIntegration.objects.update_or_create(
            user_email="owner@lifeos.local",
            defaults={"sync_enabled": True, "credentials_json": {"seed": True}},
        )
        CalendarEvent.objects.update_or_create(
            integration=integration,
            external_id="seed-standup",
            defaults={
                "title": "Team-free personal planning block",
                "start_at": now.replace(hour=15, minute=0, second=0, microsecond=0)
                if now.hour < 15
                else now + timedelta(hours=2),
                "end_at": now.replace(hour=15, minute=30, second=0, microsecond=0)
                if now.hour < 15
                else now + timedelta(hours=2, minutes=30),
                "is_blocking": True,
                "is_all_day": False,
            },
        )

        # Recurrence
        RecurrenceRule.objects.update_or_create(
            execution_item=grocery,
            defaults={
                "rrule_text": "every Sat at 10am",
                "freq": "WEEKLY",
                "byweekday": "SA",
                "byhour": 10,
                "interval": 1,
                "next_occurrence_at": now + timedelta(days=(5 - now.weekday()) % 7 or 7),
                "active": True,
            },
        )

        # Reminders
        ReminderDispatch.objects.update_or_create(
            dedupe_key=f"shell-due-{shell_item.pk}",
            defaults={
                "execution_item": shell_item,
                "kind": SystemEnums.ReminderKind.DUE_APPROACHING,
                "fire_at": now + timedelta(minutes=10),
                "status": SystemEnums.ReminderDispatchStatus.PENDING,
                "channel": "webhook_ntfy",
            },
        )
        ReminderDispatch.objects.update_or_create(
            dedupe_key=f"wg-overdue-{wg_item.pk}",
            defaults={
                "execution_item": wg_item,
                "kind": SystemEnums.ReminderKind.OVERDUE,
                "fire_at": now - timedelta(hours=1),
                "status": SystemEnums.ReminderDispatchStatus.PENDING,
                "channel": "webhook_ntfy",
            },
        )

        # Stability history
        for offset, score, band, completions, focus_s, streak in [
            (0, 78, SystemEnums.StabilityBand.STABLE, 4, 7200, 3),
            (1, 62, SystemEnums.StabilityBand.BEHIND, 2, 3600, 0),
            (2, 88, SystemEnums.StabilityBand.STABLE, 6, 9000, 2),
            (3, 45, SystemEnums.StabilityBand.OVERLOADED, 1, 10800, 0),
        ]:
            StabilitySnapshot.objects.update_or_create(
                date=today - timedelta(days=offset),
                defaults={
                    "completions_count": completions,
                    "focus_seconds": focus_s,
                    "planned_minutes": 180,
                    "index_score": score,
                    "band": band,
                    "streak_days": streak,
                },
            )

        # Saved views
        SavedView.objects.update_or_create(
            slug="tech-wip",
            defaults={
                "title": "Tech WIP",
                "target_surface": SystemEnums.SavedViewSurface.MATRIX,
                "query_params": {"domain": "tech", "status": "IN_PROGRESS,PLANNED"},
                "is_pinned": True,
            },
        )
        SavedView.objects.update_or_create(
            slug="academy-labs",
            defaults={
                "title": "Academy Labs",
                "target_surface": SystemEnums.SavedViewSurface.OVERVIEW,
                "query_params": {"domain": "academy", "tag": "lab"},
                "is_pinned": False,
            },
        )

        # Curated templates
        tmpl, _ = WorkspaceTemplate.objects.update_or_create(
            slug="software-epic",
            defaults={
                "title": "Software Epic",
                "description": "Epic → Sprint with starter implementation tasks.",
                "domain_hint": domains["tech"],
                "para_hint": SystemEnums.PARACategory.PROJECT,
                "is_active": True,
            },
        )
        WorkspaceTemplateNode.objects.filter(template=tmpl).delete()
        root_node = WorkspaceTemplateNode.objects.create(
            template=tmpl,
            title="New Software Epic",
            node_kind="container",
            container_type=SystemEnums.ContainerType.EPIC,
            order=0,
        )
        sprint_node = WorkspaceTemplateNode.objects.create(
            template=tmpl,
            parent=root_node,
            title="Sprint 1",
            node_kind="container",
            container_type=SystemEnums.ContainerType.SPRINT,
            order=1,
        )
        WorkspaceTemplateNode.objects.create(
            template=tmpl,
            parent=sprint_node,
            title="Define acceptance criteria",
            node_kind="item",
            item_type=SystemEnums.ItemType.TASK,
            estimated_minutes=30,
            order=2,
        )

        course_tmpl, _ = WorkspaceTemplate.objects.update_or_create(
            slug="course-modules",
            defaults={
                "title": "Course + Modules",
                "description": "Course with two module shells and a lab task.",
                "domain_hint": domains["academy"],
                "para_hint": SystemEnums.PARACategory.PROJECT,
                "is_active": True,
            },
        )
        WorkspaceTemplateNode.objects.filter(template=course_tmpl).delete()
        c_root = WorkspaceTemplateNode.objects.create(
            template=course_tmpl,
            title="New Course",
            node_kind="container",
            container_type=SystemEnums.ContainerType.COURSE,
            order=0,
        )
        WorkspaceTemplateNode.objects.create(
            template=course_tmpl,
            parent=c_root,
            title="Module 1",
            node_kind="container",
            container_type=SystemEnums.ContainerType.MODULE,
            order=1,
        )

        counts = {
            "domains": DomainCategory.objects.count(),
            "tags": Tag.objects.count(),
            "containers": WorkspaceContainer.objects.count(),
            "items": ExecutionItem.objects.count(),
            "links": ItemContainerLink.objects.count(),
            "deps": ItemDependencyLink.objects.count(),
            "focus": FocusSession.objects.count(),
            "allocations": ScheduledAllocation.objects.count(),
            "reminders": ReminderDispatch.objects.count(),
            "stability": StabilitySnapshot.objects.count(),
            "views": SavedView.objects.count(),
            "templates": WorkspaceTemplate.objects.count(),
        }
        self.stdout.write("Seed counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))

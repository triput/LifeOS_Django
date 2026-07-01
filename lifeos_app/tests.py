# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/tests.py
# Description: Unit and functional tests for authentication, models, and HUD logic
# Component: Core / Automated Testing
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-28
# ==============================================================================
"""Automated verification suite for the LifeOS application.

Validates security policies (auth, password hashers, single-owner restriction),
data constraints (cycles, PARA archival, soft deletion), focus actions,
and HUD context metrics.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
import datetime
import os

from .models import WorkspaceContainer, ExecutionItem, AppSettings, Tag, DomainCategory, CalendarIntegration

User = get_user_model()

class LifeOSSecurityTestCase(TestCase):
    """
    Verifies authentication controls, single-owner access restrictions, and password hashes (Section 7).
    """
    def setUp(self):
        # Create standard owner user (superuser)
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        # Create non-owner authenticated user
        self.non_owner = User.objects.create_user(
            username='non_owner_guest',
            password='AnotherPassword123!',
            email='guest@lifeos.lan'
        )
        self.client = Client()

    def test_tc_sec_001_anonymous_redirect(self):
        """Anonymous user attempts to access a protected application view. (TC-SEC-001)"""
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('login'))

    def test_tc_sec_002_owner_access(self):
        """Owner logs in and accesses a protected view. (TC-SEC-002 / TC-SEC-007)"""
        login_success = self.client.login(username='owner_trish', password='StrongSecurePassword123!')
        self.assertTrue(login_success)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_tc_sec_004_logout_invalidation(self):
        """User logs out and then attempts to access protected content. (TC-SEC-004)"""
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        # Logout
        self.client.get(reverse('logout'))
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('login'))

    def test_tc_sec_005_password_hashing(self):
        """New password is stored using the configured strong password hasher. (TC-SEC-005)"""
        # Retrieve the user record from database
        user = User.objects.get(username='owner_trish')
        # Standard Argon2 has prefix 'argon2'
        self.assertTrue(user.password.startswith('argon2'))

    def test_tc_sec_006_invalid_credentials(self):
        """Invalid credentials are rejected during login. (TC-SEC-006)"""
        response = self.client.post(reverse('login'), {
            'username': 'owner_trish',
            'password': 'WrongPassword123!'
        })
        self.assertEqual(response.status_code, 200) # Re-renders login screen
        self.assertContains(response, "Please enter a correct username and password")

    def test_tc_sec_008_non_owner_forbidden(self):
        """Authenticated non-owner account is denied access. (TC-SEC-008)"""
        self.client.login(username='non_owner_guest', password='AnotherPassword123!')
        response = self.client.get(reverse('dashboard'))
        # Returns 403 Forbidden
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "You are not authorized to access this LifeOS", status_code=403)


class LifeOSDataLifecycleTestCase(TestCase):
    """
    Verifies circular relationship prevention, PARA archival state, and soft deletions (Section 8).
    """
    def setUp(self):
        # Create base containers
        self.domain = DomainCategory.objects.get_or_create(name='Tech/Career')[0]
        self.epic = WorkspaceContainer.objects.create(
            title='Tech Career',
            container_type='Epic',
            domain=self.domain,
            para_category='Areas'
        )
        self.project = WorkspaceContainer.objects.create(
            title='LifeOS Development',
            container_type='Project',
            parent=self.epic,
            domain=self.domain,
            para_category='Projects'
        )
        
        self.container_type = ContentType.objects.get_for_model(WorkspaceContainer)
        
        # Create test execution item
        self.task = ExecutionItem.objects.create(
            title='Implement testing suite',
            item_type='Task',
            content_type=self.container_type,
            object_id=self.project.id,
            domain=self.domain,
            para_category='Projects',
            duration_estimate=60,
            time_spent_seconds=3600
        )

    def test_hierarchy_cycles(self):
        """Circular parent-child container relationships are prevented. (FR-DATA-001.3)"""
        # Setting a child as its parent's parent should fail validation
        self.epic.parent = self.project
        with self.assertRaises(ValidationError):
            self.epic.clean()

    def test_tc_life_001_soft_delete(self):
        """ExecutionItem is soft-deleted without losing timing data. (TC-LIFE-001)"""
        self.assertEqual(self.task.time_spent_seconds, 3600)
        self.task.is_deleted = True
        self.task.save()

        # Re-fetch from DB
        re_fetched = ExecutionItem.objects.get(id=self.task.id)
        self.assertTrue(re_fetched.is_deleted)
        self.assertEqual(re_fetched.time_spent_seconds, 3600) # preserved

    def test_tc_life_004_archival_preserves_data(self):
        """Archiving preserves classification and timing-related data. (TC-LIFE-004)"""
        self.task.is_archived = True
        self.task.save()

        re_fetched = ExecutionItem.objects.get(id=self.task.id)
        self.assertTrue(re_fetched.is_archived)
        self.assertEqual(re_fetched.domain.name, 'Tech/Career')
        self.assertEqual(re_fetched.para_category, 'Projects')
        self.assertEqual(re_fetched.time_spent_seconds, 3600)


class LifeOSWorkspaceTestCase(TestCase):
    """
    Verifies scoped container detail workspaces and backlog listings (Section 8).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(username='owner', password='p', email='e')
        
        self.domain = DomainCategory.objects.get_or_create(name='Academy')[0]
        self.container_active = WorkspaceContainer.objects.create(
            title='Active Course',
            container_type='Course',
            domain=self.domain,
            para_category='Areas'
        )
        self.container_archived = WorkspaceContainer.objects.create(
            title='Archived Course',
            container_type='Course',
            domain=self.domain,
            para_category='Areas',
            is_archived=True
        )
        
        self.container_type = ContentType.objects.get_for_model(WorkspaceContainer)
        
        # Actionable tasks
        self.task_active = ExecutionItem.objects.create(
            title='Active Module Homework',
            item_type='LearningTask',
            content_type=self.container_type,
            object_id=self.container_active.id,
            domain=self.domain,
            para_category='Areas'
        )
        self.task_completed = ExecutionItem.objects.create(
            title='Completed Module Homework',
            item_type='LearningTask',
            is_completed=True,
            content_type=self.container_type,
            object_id=self.container_active.id,
            domain=self.domain,
            para_category='Areas'
        )
        self.task_deleted = ExecutionItem.objects.create(
            title='Deleted Module Homework',
            item_type='LearningTask',
            is_deleted=True,
            content_type=self.container_type,
            object_id=self.container_active.id,
            domain=self.domain,
            para_category='Areas'
        )
        self.client = Client()
        self.client.force_login(self.owner)

    def test_tc_wsp_001_valid_workspace(self):
        """Valid WorkspaceContainer opens a scoped workspace view. (TC-WSP-001)"""
        response = self.client.get(reverse('container_detail', args=[self.container_active.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.container_active.title)

    def test_tc_wsp_002_invalid_workspace(self):
        """Invalid WorkspaceContainer identifier returns 404. (TC-WSP-002)"""
        response = self.client.get(reverse('container_detail', args=[999]))
        self.assertEqual(response.status_code, 404)

    def test_tc_wsp_004_backlog_exclusions(self):
        """Focused backlog hides completed, archived, and soft-deleted items by default. (TC-WSP-004 / TC-LIFE-002)"""
        response = self.client.get(reverse('container_detail', args=[self.container_active.id]))
        self.assertEqual(response.status_code, 200)
        # Verify active task is shown, completed and deleted are excluded
        self.assertContains(response, self.task_active.title)
        self.assertNotContains(response, self.task_completed.title)
        self.assertNotContains(response, self.task_deleted.title)


class LifeOSFocusEngineTestCase(TestCase):
    """
    Verifies focus transitions and timing metrics accumulation (Section 3.2).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(username='owner', password='p', email='e')
        self.container = WorkspaceContainer.objects.create(title='C', container_type='Project')
        self.container_type = ContentType.objects.get_for_model(WorkspaceContainer)
        self.task = ExecutionItem.objects.create(
            title='Focus Item',
            item_type='Task',
            content_type=self.container_type,
            object_id=self.container.id
        )
        self.client = Client()
        self.client.force_login(self.owner)

    def test_focus_start_and_stop(self):
        """Start and Stop focus commands record active time correctly."""
        # 1. Start timer
        response = self.client.post(
            reverse('task-action'),
            data={'task_id': self.task.id, 'action': 'start'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'started')

        # Verify database state
        self.task.refresh_from_db()
        self.assertTrue(self.task.is_active)
        self.assertIsNotNone(self.task.started_at)

        # Force fake duration in past to simulate active timer
        self.task.started_at = timezone.now() - datetime.timedelta(seconds=120)
        self.task.save()

        # 2. Stop timer
        response = self.client.post(
            reverse('task-action'),
            data={'task_id': self.task.id, 'action': 'stop'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'stopped')

        self.task.refresh_from_db()
        self.assertFalse(self.task.is_active)
        self.assertIsNone(self.task.started_at)
        # Should record ~120 seconds
        self.assertGreaterEqual(self.task.time_spent_seconds, 120)


class LifeOSV2FeaturesTestCase(TestCase):
    """
    Verifies V2.0 features (Quick Entry, Triage, Settings, Explorer, Analytics, Pins).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(username='owner_trish', password='StrongSecurePassword123!', email='trish@lifeos.lan')
        self.domain = DomainCategory.objects.get_or_create(name='Academy')[0]
        self.container = WorkspaceContainer.objects.create(
            title='Epic CS', 
            container_type='Epic', 
            domain=self.domain, 
            para_category='Areas'
        )
        self.client = Client()
        self.client.force_login(self.owner)

    def test_tc_inbox_001_quick_entry(self):
        """Submit a task through the global Quick Entry input. (TC-INBOX-001)"""
        response = self.client.post(
            reverse('quick-entry'),
            data={'title': 'New Brain Dump'}
        )
        # Verify redirect
        self.assertEqual(response.status_code, 302)
        
        # Verify created in DB in Inbox status with no parent
        item = ExecutionItem.objects.get(title='New Brain Dump')
        self.assertEqual(item.status, 'Inbox')
        self.assertIsNone(item.content_type)
        self.assertIsNone(item.object_id)

    def test_tc_inbox_002_triage_process(self):
        """Navigate to triage, and process a triage item to a parent. (TC-INBOX-002)"""
        item = ExecutionItem.objects.create(
            title='Untriaged Task',
            item_type='Task',
            status='Inbox'
        )
        
        # Verify visible in triage page
        response = self.client.get(reverse('triage'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.title)

        # Process the triage
        response = self.client.post(
            reverse('process-triage', args=[item.id]),
            data={
                'container': self.container.id,
                'domain': 'Academy',
                'para': 'Areas',
                'item_type': 'LearningTask',
                'priority': 'High',
                'status': 'Planned',
                'duration_estimate': 45
            }
        )
        self.assertEqual(response.status_code, 302)

        # Verify saved in DB and status changed
        item.refresh_from_db()
        self.assertEqual(item.status, 'Planned')
        self.assertEqual(item.priority, 'High')
        self.assertEqual(item.item_type, 'LearningTask')
        self.assertEqual(item.duration_estimate, 45)
        self.assertEqual(item.object_id, self.container.id)

    def test_tc_set_001_app_settings(self):
        """Open settings view, modify parameters, and save. (TC-SET-001 / TC-SET-002)"""
        response = self.client.post(
            reverse('settings'),
            data={
                'pomodoro_duration': 50,
                'start_of_work_day': '08:30',
                'enable_ai_scheduling': 'on'
            }
        )
        self.assertEqual(response.status_code, 302)

        # Verify saved to database singleton
        settings = AppSettings.get_solo()
        self.assertEqual(settings.pomodoro_duration, 50)
        self.assertEqual(settings.start_of_work_day, datetime.time(8, 30))
        self.assertTrue(settings.enable_ai_scheduling)

        # Trigger manual backup
        response = self.client.post(reverse('backup'))
        self.assertEqual(response.status_code, 302)
        # Verify backups folder created locally (checked via directory content if possible)
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backup')
        self.assertTrue(os.path.exists(backup_dir))

    def test_tc_pin_001_focus_pins(self):
        """Pin a task from the dashboard and verify status. (TC-PIN-001)"""
        container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
        item = ExecutionItem.objects.create(
            title='Pin Target Task',
            item_type='Task',
            status='Planned',
            content_type=container_ct,
            object_id=self.container.id
        )
        
        # Verify initially unpinned
        self.assertFalse(item.is_pinned)

        # Toggle Pin
        response = self.client.post(reverse('toggle-pin', args=[item.id]))
        self.assertEqual(response.status_code, 302)
        
        item.refresh_from_db()
        self.assertTrue(item.is_pinned)

        # Toggle back
        self.client.post(reverse('toggle-pin', args=[item.id]))
        item.refresh_from_db()
        self.assertFalse(item.is_pinned)

    def test_tc_life_001_lifecycle_and_priority(self):
        """Verify backlog priority sorting and status filters. (TC-LIFE-001)"""
        container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
        
        # Create an item in Backlog state
        backlog_item = ExecutionItem.objects.create(
            title='Backlog Idea',
            item_type='Task',
            status='Backlog',
            content_type=container_ct,
            object_id=self.container.id,
            priority='Low'
        )

        # Verify excluded from active backlog on dashboard
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, backlog_item.title)

        # Update to Planned and Critical priority
        backlog_item.status = 'Planned'
        backlog_item.priority = 'Critical'
        backlog_item.save()

        # Verify visible in active backlog on dashboard
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, backlog_item.title)

    def test_tc_exp_001_backlog_explorer(self):
        """Verify tree views and children loading in explorer. (TC-EXP-001)"""
        # Load main page
        response = self.client.get(reverse('explorer'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.container.title)

        # Lazy-load children of self.container
        response = self.client.get(
            reverse('explorer-children'),
            {'parent_type': 'container', 'parent_id': self.container.id}
        )
        self.assertEqual(response.status_code, 200)
        # Should render empty child list since container has no children
        self.assertContains(response, "No nested containers or tasks")


class LifeOSV3FeaturesTestCase(TestCase):
    """
    Verifies V3.0 upgrades including dynamic domains, human-readable time logs,
    recursive rollups, automatic recurrence engines, and integrations (Section 9).
    """
    def setUp(self):
        from .models import DomainCategory
        self.owner = User.objects.create_superuser(username='owner_v3', password='pw', email='v3@lifeos.lan')
        self.client = Client()
        self.client.login(username='owner_v3', password='pw')

        # Create base academic domain
        self.domain, _ = DomainCategory.objects.get_or_create(
            name='Special Academy',
            defaults={
                'color': '#9966CC',
                'icon': 'academic-cap',
                'is_academy': True
            }
        )

    def test_dynamic_domains(self):
        """Verify dynamic domain creation and settings forms."""
        response = self.client.post(reverse('domain-add'), {
            'name': 'Home Tasks',
            'color': '#FF5733',
            'icon': 'home',
        })
        self.assertEqual(response.status_code, 302)
        
        from .models import DomainCategory
        self.assertTrue(DomainCategory.objects.filter(name='Home Tasks').exists())
        
        # Test deletion
        target = DomainCategory.objects.get(name='Home Tasks')
        response = self.client.post(reverse('domain-delete', args=[target.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DomainCategory.objects.filter(name='Home Tasks').exists())

    def test_human_duration_parsing(self):
        """Verify duration helpers correctly parse complex strings."""
        from .models import parse_duration_to_seconds, format_seconds_to_duration
        self.assertEqual(parse_duration_to_seconds("45"), 45 * 60)
        self.assertEqual(parse_duration_to_seconds("1h 30m"), 90 * 60)
        self.assertEqual(parse_duration_to_seconds("2d 3h"), (48 + 3) * 3600)
        self.assertEqual(parse_duration_to_seconds("1w"), 7 * 24 * 3600)
        
        self.assertEqual(format_seconds_to_duration(3600), "1h")
        self.assertEqual(format_seconds_to_duration(90), "1m 30s")

    def test_recursive_time_rollups(self):
        """Verify cascading rollups from subtask to task to container."""
        from .models import WorkspaceContainer, ExecutionItem
        epic = WorkspaceContainer.objects.create(
            title='Study Epic',
            container_type='Epic',
            domain=self.domain
        )
        task = ExecutionItem.objects.create(
            title='Main Task',
            item_type='Task',
            content_type=ContentType.objects.get_for_model(WorkspaceContainer),
            object_id=epic.id,
            time_spent_seconds=1000,
            extra_actual_seconds=500
        )
        
        # Subtask under task
        subtask = ExecutionItem.objects.create(
            title='Subtask Task',
            item_type='Task',
            content_type=ContentType.objects.get_for_model(ExecutionItem),
            object_id=task.id,
            time_spent_seconds=800,
            extra_actual_seconds=200
        )
        
        # Assertions
        # subtask total = 800 + 200 = 1000s
        self.assertEqual(subtask.get_total_time_spent_seconds(), 1000)
        # task total = 1000 (direct) + 500 (extra) + 1000 (subtask) = 2500s
        self.assertEqual(task.get_total_time_spent_seconds(), 2500)
        # epic total = 2500 (from task)
        self.assertEqual(epic.get_total_time_spent_seconds(), 2500)
        self.assertEqual(epic.total_time_duration_str, "41m 40s")

    def test_recurrence_cloning(self):
        """Verify auto-recurrence config clones new item upon completion."""
        from .models import ExecutionItem, RecurringConfig
        item = ExecutionItem.objects.create(
            title='Daily Standup',
            item_type='Task',
            status='Planned',
            is_completed=False,
            due_date=timezone.now()
        )
        RecurringConfig.objects.create(
            execution_item=item,
            frequency='Daily'
        )
        
        # Complete the item to trigger recurrence hook
        from .models import Tag
        tag = Tag.objects.create(name='RecurTag', color='#111111')
        item.tags.add(tag)
        item.is_completed = True
        item.save()
        
        # Verify a new Planned item is created
        clones = ExecutionItem.objects.filter(title='Daily Standup', is_completed=False)
        self.assertEqual(clones.count(), 1)
        clone = clones.first()
        self.assertEqual(clone.status, 'Planned')
        self.assertIsNotNone(clone.due_date)
        self.assertIn(tag, clone.tags.all())

    def test_certifications_hud(self):
        """Verify certifications creation and PDU progress metrics."""
        response = self.client.post(reverse('certification-add'), {
            'title': 'Certified Scrum Master',
            'achieved_date': '2026-01-01',
            'renewal_date': '2028-01-01',
            'pdus_required': '40',
            'pdus_earned': '20',
        })
        self.assertEqual(response.status_code, 302)
        
        from .models import Certification
        self.assertTrue(Certification.objects.filter(title='Certified Scrum Master').exists())
        
        # Verify list displays on academy view
        response = self.client.get(reverse('academy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Certified Scrum Master')
        self.assertContains(response, '20 / 40')

    def test_weather_imperial_units(self):
        """Verify OpenMeteoAdapter requests fahrenheit when use_imperial settings is checked."""
        from .telemetry import OpenMeteoAdapter
        from .models import AppSettings
        from unittest.mock import patch
        
        settings = AppSettings.get_solo()
        settings.use_imperial = True
        settings.save()
        
        adapter = OpenMeteoAdapter()
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "current": {"temperature_2m": 72.5},
                "current_units": {"temperature_2m": "°F"},
                "daily": {"sunrise": ["2026-06-27T05:30:00"], "sunset": ["2026-06-27T21:15:00"]}
            }
            res = adapter.get_telemetry()
            
            self.assertTrue(mock_get.called)
            kwargs = mock_get.call_args[1]
            params = kwargs.get('params', {})
            self.assertEqual(params.get('temperature_unit'), 'fahrenheit')
            self.assertEqual(res.get('temperature'), '72.5°F')
            
        settings.use_imperial = False
        settings.save()
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "current": {"temperature_2m": 22.5},
                "current_units": {"temperature_2m": "°C"},
                "daily": {"sunrise": ["2026-06-27T05:30:00"], "sunset": ["2026-06-27T21:15:00"]}
            }
            res = adapter.get_telemetry()
            self.assertTrue(mock_get.called)
            kwargs = mock_get.call_args[1]
            params = kwargs.get('params', {})
            self.assertNotIn('temperature_unit', params)
            self.assertEqual(res.get('temperature'), '22.5°C')

    def test_weather_timezone_sanitization(self):
        """Verify OpenMeteoAdapter sanitizes abbreviation timezones (e.g. PDT -> auto)."""
        from .telemetry import OpenMeteoAdapter
        from .models import AppSettings
        from unittest.mock import patch
        
        settings = AppSettings.get_solo()
        settings.timezone = "PDT"
        settings.save()
        
        adapter = OpenMeteoAdapter()
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "current": {"temperature_2m": 22.5},
                "current_units": {"temperature_2m": "°C"},
                "daily": {"sunrise": ["2026-06-27T05:30:00"], "sunset": ["2026-06-27T21:15:00"]}
            }
            res = adapter.get_telemetry()
            
            self.assertTrue(mock_get.called)
            kwargs = mock_get.call_args[1]
            params = kwargs.get('params', {})
            self.assertEqual(params.get('timezone'), 'auto') # PDT sanitized to auto!


from unittest.mock import patch, MagicMock
from .scheduler import calculate_rank_score, generate_schedule_for_date
from .slm_parser import parse_natural_language_constraints, SLMParseError

class V4SchedulerTests(TestCase):
    def setUp(self):
        self.settings = AppSettings.get_solo()
        self.settings.enable_ai_scheduling = True
        self.settings.priority_weight = 1.5
        self.settings.urgency_weight = 2.0
        self.settings.save()
        
        self.item_critical_immediate = ExecutionItem.objects.create(
            title="Critical Immediate", item_type="Task", status="Planned",
            priority="Critical", urgency="Immediate", duration_estimate=30
        )
        self.item_low_low = ExecutionItem.objects.create(
            title="Low Low", item_type="Task", status="Planned",
            priority="Low", urgency="Low", duration_estimate=60
        )
        
    def test_calculate_rank_score(self):
        # Critical(4) * 1.5 + Immediate(4) * 2.0 - (30 * 0.05) = 6.0 + 8.0 - 1.5 = 12.5
        score_high = calculate_rank_score(self.item_critical_immediate, self.settings)
        self.assertEqual(score_high, 12.5)
        
        # Low(1) * 1.5 + Low(1) * 2.0 - (60 * 0.05) = 1.5 + 2.0 - 3.0 = 0.5
        score_low = calculate_rank_score(self.item_low_low, self.settings)
        self.assertEqual(score_low, 0.5)

    def test_generate_schedule_fallback_block(self):
        target_date = timezone.now().date() + datetime.timedelta(days=1)
        generate_schedule_for_date(target_date)
        
        # Verify allocations were created
        self.item_critical_immediate.refresh_from_db()
        self.item_low_low.refresh_from_db()
        
        self.assertTrue(hasattr(self.item_critical_immediate, 'scheduled_allocation'))
        self.assertTrue(hasattr(self.item_low_low, 'scheduled_allocation'))
        
        # Critical immediate should be scheduled FIRST
        alloc1 = self.item_critical_immediate.scheduled_allocation
        alloc2 = self.item_low_low.scheduled_allocation
        
        self.assertTrue(alloc1.start_time <= alloc2.start_time)


class V4SLMParserTests(TestCase):
    def setUp(self):
        self.settings = AppSettings.get_solo()
        
    @patch('lifeos_app.slm_parser.requests.post')
    def test_slm_parser_success(self, mock_post):
        self.settings.slm_provider = 'Local Ollama'
        self.settings.save()
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response': '{"title": "Do something", "duration_minutes": 60, "priority": "High", "urgency": "Normal"}'
        }
        mock_post.return_value = mock_response
        
        result = parse_natural_language_constraints("Do something high priority")
        self.assertEqual(result.get('duration_minutes'), 60)
        self.assertEqual(result.get('priority'), 'High')

    def test_slm_parser_skipped(self):
        self.settings.slm_provider = 'Skip'
        self.settings.save()
        
        with self.assertRaises(SLMParseError):
            parse_natural_language_constraints("Do something")


class V5FeatureTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        self.client = Client()
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')
        
        self.domain = DomainCategory.objects.get_or_create(name="Engineering")[0]
        
        # Create some tags
        self.tag_urgent = Tag.objects.create(name="Urgent", color="#FF0000")
        self.tag_feature = Tag.objects.create(name="Feature", color="#00FF00")
        self.tag_bug = Tag.objects.create(name="Bug", color="#0000FF")
        
        # Create a container
        self.container = WorkspaceContainer.objects.create(
            title="V5 Engine Upgrade",
            container_type="Project",
            domain=self.domain,
            priority="High",
            urgency="Immediate"
        )
        self.container.tags.add(self.tag_urgent, self.tag_feature)
        
        # Create an orphaned container
        self.orphan_container = WorkspaceContainer.objects.create(
            title="Quick Dump Container",
            container_type="Project",
            priority="Medium",
            urgency="Normal"
        )
        
        # Create an execution item in inbox
        self.inbox_item = ExecutionItem.objects.create(
            title="Fix login bug",
            item_type="Task",
            status="Inbox",
            priority="Critical",
            urgency="High"
        )
        self.inbox_item.tags.add(self.tag_bug)
        
        # Create a planned execution item
        self.planned_item = ExecutionItem.objects.create(
            title="Implement Tagging",
            item_type="Task",
            status="Planned",
            priority="Medium",
            urgency="Normal",
            content_type=ContentType.objects.get_for_model(WorkspaceContainer),
            object_id=self.container.id
        )
        self.planned_item.tags.add(self.tag_feature)

    def test_container_priority_and_urgency(self):
        """Test that Priority and Urgency are properly saved and retrieved on WorkspaceContainers"""
        self.assertEqual(self.container.priority, "High")
        self.assertEqual(self.container.urgency, "Immediate")
        
    def test_item_priority_and_urgency(self):
        """Test that Priority and Urgency are properly saved and retrieved on ExecutionItems"""
        self.assertEqual(self.inbox_item.priority, "Critical")
        self.assertEqual(self.inbox_item.urgency, "High")

    def test_tagging_system_relations(self):
        """Test that the ManyToMany tag relations are functioning"""
        self.assertIn(self.tag_urgent, self.container.tags.all())
        self.assertIn(self.tag_bug, self.inbox_item.tags.all())
        self.assertEqual(self.container.tags.count(), 2)

    def test_backlog_explorer_filtering(self):
        """Test the ?tags= query filtering logic on the explorer endpoint"""
        # Test filtering by a tag that belongs to the container
        response = self.client.get(reverse('explorer') + f"?tags={self.tag_urgent.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.container, response.context['root_containers'])
        
        # Test filtering by a tag that DOES NOT belong to the container
        response = self.client.get(reverse('explorer') + f"?tags={self.tag_bug.id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.container, response.context['root_containers'])

    def test_triage_view_orphan_containers(self):
        """Test that orphaned containers (no domain, no parent) appear in Triage"""
        response = self.client.get(reverse('triage'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.orphan_container, response.context['orphan_containers'])
        self.assertNotIn(self.container, response.context['orphan_containers'])

    def test_process_triage_default_to_backlog(self):
        """Test processing an Inbox item without dates correctly sets status to Backlog"""
        post_data = {
            'container': f'container_{self.container.id}',
            'domain': self.domain.name,
            'para': 'Projects',
            'item_type': 'Task',
            'priority': 'High',
            'status': ''
        }
        
        response = self.client.post(reverse('process-triage', args=[self.inbox_item.id]), post_data)
        
        self.inbox_item.refresh_from_db()
        
        self.assertEqual(self.inbox_item.status, 'Backlog')
        self.assertEqual(self.inbox_item.content_type.model, 'workspacecontainer')
        self.assertEqual(self.inbox_item.object_id, self.container.id)

    def test_triage_container_circular_dependency_graceful_error(self):
        """Test that triaging a container with circular dependency does not crash with 500, but redirects gracefully with message"""
        # Create a child container
        child_container = WorkspaceContainer.objects.create(
            title="Child",
            container_type="Project",
            parent=self.orphan_container
        )
        
        # Now try to triage the orphan container and assign its parent to child_container (creates circular dependency: orphan -> child -> orphan)
        post_data = {
            'container': f'container_{child_container.id}',
            'domain': self.domain.name,
            'para': 'Projects'
        }
        
        response = self.client.post(reverse('process-container-triage', args=[self.orphan_container.id]), post_data)
        
        # Check that it redirected back to triage
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith(reverse('triage')))
        
        # Verify database is intact (orphan_container parent is still None)
        self.orphan_container.refresh_from_db()
        self.assertIsNone(self.orphan_container.parent)


class LifeOSGridEditorTestCase(TestCase):
    """
    Verifies the Hierarchical Backlog Grid Editor endpoints (V5.1).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        self.client = Client()
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')
        
        self.domain = DomainCategory.objects.get_or_create(name="Engineering")[0]
        
        self.container = WorkspaceContainer.objects.create(
            title="Grid Project",
            container_type="Project",
            domain=self.domain
        )
        self.task = ExecutionItem.objects.create(
            title="Grid Task",
            item_type="Task",
            status="Planned",
            domain=self.domain
        )

    def test_grid_editor_views_require_login(self):
        # Logout first
        self.client.logout()
        response = self.client.get(reverse('explorer-grid'))
        self.assertRedirects(response, reverse('login'))

    def test_grid_editor_view_success(self):
        response = self.client.get(reverse('explorer-grid'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Grid Project")
        self.assertContains(response, "Grid Task")

    def test_grid_editor_save_field_container(self):
        response = self.client.post(reverse('explorer-grid-save-field'), {
            'model_type': 'container',
            'model_id': self.container.id,
            'field': 'title',
            'value': 'Updated Grid Project Title'
        })
        self.assertEqual(response.status_code, 200)
        self.container.refresh_from_db()
        self.assertEqual(self.container.title, 'Updated Grid Project Title')

    def test_grid_editor_save_field_item(self):
        response = self.client.post(reverse('explorer-grid-save-field'), {
            'model_type': 'item',
            'model_id': self.task.id,
            'field': 'priority',
            'value': 'Critical'
        })
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.priority, 'Critical')

    def test_grid_editor_add_row_container(self):
        response = self.client.post(reverse('explorer-grid-add-row'), {
            'parent_type': 'container',
            'parent_id': self.container.id,
            'row_type': 'WorkspaceContainer',
            'depth': '1'
        })
        self.assertEqual(response.status_code, 200)
        # Verify a new container is created in the database and linked to the parent
        new_container = WorkspaceContainer.objects.get(title="New Container", parent=self.container)
        self.assertEqual(new_container.domain, self.domain)

    def test_grid_editor_add_row_task(self):
        response = self.client.post(reverse('explorer-grid-add-row'), {
            'parent_type': 'container',
            'parent_id': self.container.id,
            'row_type': 'Task',
            'depth': '1'
        })
        self.assertEqual(response.status_code, 200)
        # Verify a new task is created and linked
        new_task = ExecutionItem.objects.get(title="New Task", object_id=self.container.id)
        self.assertEqual(new_task.domain, self.domain)

    def test_grid_editor_save_tags(self):
        tag1 = Tag.objects.create(name="Tag 1", color="#FF0000")
        tag2 = Tag.objects.create(name="Tag 2", color="#00FF00")
        
        response = self.client.post(reverse('explorer-grid-save-field'), {
            'model_type': 'item',
            'model_id': self.task.id,
            'field': 'tags',
            'value': [tag1.id, tag2.id]
        })
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertIn(tag1, self.task.tags.all())
        self.assertIn(tag2, self.task.tags.all())

    def test_grid_editor_create_tag(self):
        response = self.client.post(reverse('explorer-grid-create-tag'), {
            'model_type': 'item',
            'model_id': self.task.id,
            'tag_name': 'Brand New Tag',
            'depth': '0'
        })
        self.assertEqual(response.status_code, 200)
        # Verify tag exists and is assigned
        tag = Tag.objects.get(name="Brand New Tag")
        self.task.refresh_from_db()
        self.assertIn(tag, self.task.tags.all())

    def test_tag_crud_operations(self):
        # 1. Add tag
        response = self.client.post(reverse('tag-add'), {
            'name': 'Pending Feedback',
            'color': '#FFA500'
        })
        self.assertEqual(response.status_code, 302)
        tag = Tag.objects.get(name='Pending Feedback')
        self.assertEqual(tag.color, '#FFA500')

        # 2. Edit tag
        response = self.client.post(reverse('tag-edit', args=[tag.id]), {
            'name': 'Feedback Requested',
            'color': '#FF8C00'
        })
        self.assertEqual(response.status_code, 302)
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'Feedback Requested')
        self.assertEqual(tag.color, '#FF8C00')

        # 3. Safe Deletion Rule (fails if in use)
        self.task.tags.add(tag)
        
        # Verify tag association statistics
        counts = tag.get_association_counts()
        self.assertEqual(counts['total'], 1)
        self.assertEqual(counts['items']['Task'], 1)
        
        response = self.client.post(reverse('tag-delete', args=[tag.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Tag.objects.filter(id=tag.id).exists()) # still exists because in use

        # 4. Successful Deletion (after clearing references)
        self.task.tags.clear()
        response = self.client.post(reverse('tag-delete', args=[tag.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tag.objects.filter(id=tag.id).exists())

    def test_tag_retag_operations(self):
        tag_a = Tag.objects.create(name="Tag A", color="#FF0000")
        tag_b = Tag.objects.create(name="Tag B", color="#00FF00")
        
        self.task.tags.add(tag_a)
        self.container.tags.add(tag_a)
        
        # 1. Bulk Retag Tag A -> Tag B
        response = self.client.post(reverse('tag-retag', args=[tag_a.id]), {
            'target_tag_id': tag_b.id
        })
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.container.refresh_from_db()
        
        # Verify Tag A is gone and Tag B is present
        self.assertNotIn(tag_a, self.task.tags.all())
        self.assertIn(tag_b, self.task.tags.all())
        self.assertNotIn(tag_a, self.container.tags.all())
        self.assertIn(tag_b, self.container.tags.all())
        
        # 2. Bulk Clear Tag B
        response = self.client.post(reverse('tag-retag', args=[tag_b.id]), {
            'target_tag_id': 'clear'
        })
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.container.refresh_from_db()
        self.assertNotIn(tag_b, self.task.tags.all())
        self.assertNotIn(tag_b, self.container.tags.all())

    def test_explicit_time_scheduling_solver(self):
        from unittest.mock import patch
        from django.utils import timezone
        import datetime
        from .scheduler import generate_schedule_for_date
        
        # Enable scheduling in settings
        settings = AppSettings.get_solo()
        settings.enable_ai_scheduling = True
        settings.save()
        
        target_date = timezone.now().date()
        
        # Mock SLM response return containing explicit target_time
        mock_response = {
            "title": "Specific Time Task",
            "duration_minutes": 60,
            "priority": "High",
            "urgency": "High",
            "target_date": target_date.isoformat(),
            "target_time": "15:30",
            "time_of_day": None
        }
        
        with patch('lifeos_app.slm_parser.parse_natural_language_constraints', return_value=mock_response):
            response = self.client.post(reverse('planner-parse-nl'), {
                'nl_text': 'Specific Time Task at 3:30PM'
            })
            self.assertEqual(response.status_code, 200)
            
            # Check execution item is created with correct explicit times
            task = ExecutionItem.objects.get(title="Specific Time Task")
            self.assertIsNotNone(task.start_date)
            self.assertEqual(task.start_date.hour, 15)
            self.assertEqual(task.start_date.minute, 30)
            
            # Check scheduler created the correct allocation
            alloc = task.scheduled_allocation
            self.assertEqual(alloc.start_time.hour, 15)
            self.assertEqual(alloc.start_time.minute, 30)

    def test_timezone_activation_and_parser_baseline(self):
        from django.utils import timezone
        
        # Configure a specific timezone
        settings = AppSettings.get_solo()
        settings.timezone = 'America/New_York'
        settings.save()
        
        # Verify timezone activation middleware
        # Making a request should trigger OwnerOnlyAccessMiddleware which activates the timezone
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(timezone.get_current_timezone_name(), 'America/New_York')


class LifeOSEditDrawerTestCase(TestCase):
    """
    Verifies the functionality of the sliding detail edit drawer (GET and POST).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        self.client = Client()
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')

        # Create basic Domain and Tags
        self.domain, _ = DomainCategory.objects.get_or_create(name="Academy", defaults={"is_academy": True, "color": "#50C878"})
        self.tag1 = Tag.objects.create(name="Exam Prep", color="#E0115F")
        self.tag2 = Tag.objects.create(name="Study Session", color="#0F52BA")

        # Create workspace container and item
        self.container = WorkspaceContainer.objects.create(
            title="PMP Course",
            container_type="Course",
            domain=self.domain,
            priority="High",
            urgency="Normal"
        )
        self.item = ExecutionItem.objects.create(
            title="Read Chapter 1",
            item_type="Task",
            status="Backlog",
            priority="Medium",
            urgency="Normal",
            domain=self.domain
        )

    def test_tc_drawer_get_container(self):
        """GET request for container details drawer returns status 200 and details. (TC-DRAWER-001)"""
        url = reverse('explorer-grid-modal', kwargs={'model_type': 'container', 'model_id': self.container.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PMP Course")
        self.assertContains(response, "Container Details")

    def test_tc_drawer_get_item(self):
        """GET request for execution item details drawer returns status 200 and details. (TC-DRAWER-002)"""
        url = reverse('explorer-grid-modal', kwargs={'model_type': 'item', 'model_id': self.item.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Read Chapter 1")
        self.assertContains(response, "Task Details")

    def test_tc_drawer_post_container(self):
        """POST request updates container fields and returns updated grid row. (TC-DRAWER-003)"""
        url = reverse('explorer-grid-modal', kwargs={'model_type': 'container', 'model_id': self.container.id})
        payload = {
            'title': 'PMP Exam Course Updated',
            'container_type': 'Specialization',
            'domain_id': self.domain.id,
            'priority': 'Critical',
            'urgency': 'Immediate',
            'parent_id': 'none',
            'tags': [self.tag1.id, self.tag2.id],
            'depth': '1'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify object was saved
        self.container.refresh_from_db()
        self.assertEqual(self.container.title, 'PMP Exam Course Updated')
        self.assertEqual(self.container.priority, 'Critical')
        self.assertEqual(self.container.urgency, 'Immediate')
        self.assertEqual(self.container.tags.count(), 2)
        
        # Verify response contains the close drawer OOB swap element
        self.assertContains(response, 'hx-swap-oob="innerHTML"')

    def test_tc_drawer_post_item(self):
        """POST request updates execution item fields and returns updated grid row. (TC-DRAWER-004)"""
        url = reverse('explorer-grid-modal', kwargs={'model_type': 'item', 'model_id': self.item.id})
        payload = {
            'title': 'Read Chapter 1 & 2',
            'item_type': 'LearningTask',
            'status': 'In Progress',
            'domain_id': self.domain.id,
            'priority': 'High',
            'urgency': 'High',
            'duration_estimate': '1h 30m',
            'extra_actual_time': '30m',
            'fuzzy_timeframe': 'Today',
            'tags': [self.tag1.id],
            'depth': '0'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify object was saved
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Read Chapter 1 & 2')
        self.assertEqual(self.item.item_type, 'LearningTask')
        self.assertEqual(self.item.status, 'In Progress')
        self.assertTrue(self.item.is_completed is False)
        self.assertEqual(self.item.duration_estimate, 90)
        self.assertEqual(self.item.extra_actual_seconds, 1800)
        self.assertEqual(self.item.fuzzy_timeframe, 'Today')
        
        # Verify response contains the close drawer OOB swap element
        self.assertContains(response, 'hx-swap-oob="innerHTML"')

    def test_tc_drawer_post_dashboard(self):
        """POST request from dashboard updates task and returns HX-Refresh header. (TC-DRAWER-005)"""
        url = reverse('explorer-grid-modal', kwargs={'model_type': 'item', 'model_id': self.item.id})
        payload = {
            'title': 'Read Chapter 1 & 2',
            'item_type': 'LearningTask',
            'status': 'In Progress',
            'domain_id': self.domain.id,
            'priority': 'High',
            'urgency': 'High',
            'duration_estimate': '1h 30m',
            'extra_actual_time': '30m',
            'fuzzy_timeframe': 'Today',
            'tags': [self.tag1.id],
            'depth': '0',
            'source': 'dashboard'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('HX-Refresh'), 'true')
        
        # Verify object was saved
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Read Chapter 1 & 2')


class LifeOSGridBulkActionTestCase(TestCase):
    """
    Verifies the functionality of bulk grid actions (status shifts, reparenting, tagging, dates).
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        self.client = Client()
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')

        self.domain, _ = DomainCategory.objects.get_or_create(name="Academy", defaults={"is_academy": True, "color": "#50C878"})
        self.tag1 = Tag.objects.create(name="Required", color="#E0115F")

        # Create multiple containers and tasks
        self.container_a = WorkspaceContainer.objects.create(title="Course A", container_type="Course", domain=self.domain)
        self.container_b = WorkspaceContainer.objects.create(title="Course B", container_type="Course", domain=self.domain)
        
        self.task_1 = ExecutionItem.objects.create(title="Task 1", item_type="Task", status="Backlog", domain=self.domain)
        self.task_2 = ExecutionItem.objects.create(title="Task 2", item_type="Task", status="Backlog", domain=self.domain)

    def test_tc_bulk_archive(self):
        """POST request bulk archives selected containers and items. (TC-BULK-001)"""
        url = reverse('explorer-grid-bulk-action')
        payload = {
            'action': 'archive',
            'selected_items': [self.task_1.id, self.task_2.id],
            'selected_containers': [self.container_a.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('HX-Refresh'), 'true')

        self.task_1.refresh_from_db()
        self.task_2.refresh_from_db()
        self.container_a.refresh_from_db()

        self.assertTrue(self.task_1.is_archived)
        self.assertTrue(self.task_2.is_archived)
        self.assertTrue(self.container_a.is_archived)

    def test_tc_bulk_status(self):
        """POST request bulk shifts status of selected items. (TC-BULK-002)"""
        url = reverse('explorer-grid-bulk-action')
        payload = {
            'action': 'status',
            'bulk_status': 'Completed',
            'selected_items': [self.task_1.id, self.task_2.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.task_2.refresh_from_db()

        self.assertEqual(self.task_1.status, 'Completed')
        self.assertTrue(self.task_1.is_completed)
        self.assertEqual(self.task_2.status, 'Completed')
        self.assertTrue(self.task_2.is_completed)

    def test_tc_bulk_reparent(self):
        """POST request bulk reparents items and containers under selected project. (TC-BULK-003)"""
        url = reverse('explorer-grid-bulk-action')
        payload = {
            'action': 'reparent',
            'bulk_parent': self.container_a.id,
            'selected_items': [self.task_1.id],
            'selected_containers': [self.container_b.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.container_b.refresh_from_db()

        # Task 1 is parented to container_a
        self.assertEqual(self.task_1.object_id, self.container_a.id)
        # Container B is parented to container_a
        self.assertEqual(self.container_b.parent.id, self.container_a.id)

    def test_tc_bulk_tagging(self):
        """POST request bulk tags/untags selected items and containers. (TC-BULK-004)"""
        url = reverse('explorer-grid-bulk-action')
        # Add tag
        payload = {
            'action': 'add_tag',
            'bulk_tag': self.tag1.id,
            'selected_items': [self.task_1.id],
            'selected_containers': [self.container_a.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.container_a.refresh_from_db()
        self.assertIn(self.tag1, self.task_1.tags.all())
        self.assertIn(self.tag1, self.container_a.tags.all())

        # Remove tag
        payload = {
            'action': 'remove_tag',
            'bulk_tag': self.tag1.id,
            'selected_items': [self.task_1.id],
            'selected_containers': [self.container_a.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.container_a.refresh_from_db()
        self.assertNotIn(self.tag1, self.task_1.tags.all())
        self.assertNotIn(self.tag1, self.container_a.tags.all())

    def test_tc_bulk_scheduling(self):
        """POST request bulk schedules selected tasks. (TC-BULK-005)"""
        url = reverse('explorer-grid-bulk-action')
        payload = {
            'action': 'set_dates',
            'bulk_start_date': '2026-07-01T09:00',
            'bulk_due_date': '2026-07-02T18:00',
            'selected_items': [self.task_1.id, self.task_2.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.task_2.refresh_from_db()

        self.assertIsNotNone(self.task_1.start_date)
        self.assertIsNotNone(self.task_1.due_date)
        self.assertEqual(self.task_1.start_date.month, 7)
        self.assertEqual(self.task_2.due_date.day, 2)

    def test_tc_bulk_fuzzy_scheduling(self):
        """POST request bulk schedules selected tasks via fuzzy timeframe. (TC-BULK-006)"""
        url = reverse('explorer-grid-bulk-action')
        payload = {
            'action': 'set_fuzzy',
            'bulk_fuzzy_timeframe': 'Tomorrow',
            'selected_items': [self.task_1.id, self.task_2.id]
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        self.task_1.refresh_from_db()
        self.task_2.refresh_from_db()

        self.assertEqual(self.task_1.fuzzy_timeframe, 'Tomorrow')
        self.assertIsNotNone(self.task_1.start_date)
        self.assertIsNotNone(self.task_2.start_date)
        
        # Verify it creates allocations for the date (solver was run)
        self.assertIsNotNone(self.task_1.scheduled_allocation)
        self.assertIsNotNone(self.task_2.scheduled_allocation)


class LifeOSPhase5TestCase(TestCase):
    """
    Unit tests for Phase 5 scheduling, date cascading, and boundary checker.
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='owner_trish',
            password='StrongSecurePassword123!',
            email='trish@lifeos.lan'
        )
        self.client = Client()
        self.client.login(username='owner_trish', password='StrongSecurePassword123!')
        
        self.settings = AppSettings.get_solo()
        self.domain, _ = DomainCategory.objects.get_or_create(name="Academy", defaults={"is_academy": True, "color": "#50C878"})

    def test_container_date_cascading(self):
        # Create container
        parent = WorkspaceContainer.objects.create(title="Parent Course", container_type="Course", domain=self.domain)
        child = WorkspaceContainer.objects.create(title="Child Module", container_type="Module", parent=parent, domain=self.domain)
        item = ExecutionItem.objects.create(
            title="Child Task",
            item_type="Task",
            content_type=ContentType.objects.get_for_model(WorkspaceContainer),
            object_id=child.id,
            domain=self.domain
        )
        
        # Edit container via views to trigger cascading
        url = reverse('explorer-edit', kwargs={'node_type': 'container', 'node_id': parent.id})
        payload = {
            'title': parent.title,
            'container_type': parent.container_type,
            'domain_id': self.domain.id,
            'start_date': '2026-07-10T09:00',
            'end_date': '2026-07-20T18:00',
            'due_date': '2026-07-20T18:00',
            'respect_child_dates': 'off'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302) # Redirect on success
        
        parent.refresh_from_db()
        child.refresh_from_db()
        item.refresh_from_db()
        
        # Check child dates match parent
        self.assertIsNotNone(child.start_date)
        self.assertEqual(child.start_date, parent.start_date)
        self.assertEqual(item.start_date, parent.start_date)

    def test_check_bounds_api(self):
        parent = WorkspaceContainer.objects.create(title="Parent Course", container_type="Course", domain=self.domain)
        child = WorkspaceContainer.objects.create(title="Child Module", container_type="Module", parent=parent, domain=self.domain)
        import datetime
        child.start_date = datetime.datetime(2026, 7, 12, 9, 0, tzinfo=datetime.timezone.utc)
        child.due_date = datetime.datetime(2026, 7, 15, 18, 0, tzinfo=datetime.timezone.utc)
        child.save()
        
        # Call check-bounds view with bounds that overlap child via POST
        url = reverse('container-check-bounds', kwargs={'container_id': parent.id})
        response = self.client.post(url, {
            'start_date': '2026-07-13T09:00',
            'end_date': '2026-07-14T18:00'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data['conflicts']) > 0)
        self.assertEqual(len(data['conflicts']), 1)


class LifeOSSecurityUpgradesTestCase(TestCase):
    """
    Verifies Phase 1 security improvements, token encryption, and view access limits.
    """
    def setUp(self):
        self.owner = User.objects.create_superuser(username='owner_trish', password='StrongSecurePassword123!', email='trish@lifeos.lan')
        self.client = Client()

    def test_credentials_encryption_cycle(self):
        """Credentials JSON should be encrypted prior to save, and decrypted on read."""
        integ = CalendarIntegration.objects.create(
            user_email="trish@lifeos.lan",
            credentials_json={"token": "supersecrettokenvalue", "refresh_token": "refreshvalue"}
        )
        
        # Accessing via helper method should decrypt it
        decrypted = integ.get_credentials()
        self.assertEqual(decrypted["token"], "supersecrettokenvalue")
        self.assertEqual(decrypted["refresh_token"], "refreshvalue")

    def test_view_auth_decorators(self):
        """Verify that protected views redirect unauthenticated users to login page."""
        protected_urls = [
            reverse('dashboard'),
            reverse('settings'),
            reverse('explorer'),
            reverse('planner'),
            reverse('analytics'),
            reverse('explorer-grid'),
            reverse('triage'),
            reverse('kanban-status'),
            reverse('academy'),
        ]
        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('login'), response.url)



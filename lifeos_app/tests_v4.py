# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/tests_v4.py
# Description: Automated tests for V4 SLM scheduling engine
# Component: Testing
# Version: 1.0 (Gold Master)
# Created: 2026-06-27
# Last Update: 2026-06-27
# ==============================================================================

import datetime
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock

from .models import (
    ExecutionItem, AppSettings, GoogleCalendarEvent, 
    TimeAvailabilityBlock, ScheduledTaskAllocation, GoogleCalendar
)
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
            'response': '{"duration_minutes": 60, "priority": "High", "urgency": "Normal"}'
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

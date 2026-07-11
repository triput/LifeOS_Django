# ==============================================================================
# File: lifeos_app/tests/test_notify_adapters.py
# Description: BL-NOTIFY-001 webhook channel adapter tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Unit tests for ntfy / Gotify / raw JSON webhook adapters."""

import json
from unittest.mock import patch

from django.test import TestCase

from lifeos_app.models import SystemEnums
from lifeos_app.services.notify import (
    ReminderPayload,
    build_webhook_request,
    deliver_webhook,
    dispatch_channel_name,
    send_test_webhook,
)
from lifeos_app.services.settings_surface import save_notification_settings


class NotifyAdapterTests(TestCase):
    def _payload(self) -> ReminderPayload:
        return ReminderPayload(
            title="Review quarterly report",
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            item_id=42,
            dedupe_key="item-42-due",
            fire_at="2026-07-09T18:00:00+00:00",
        )

    def test_ntfy_request_shape(self):
        req = build_webhook_request(
            channel="ntfy",
            url="https://ntfy.example.com/lifeos",
            token="secret",
            payload=self._payload(),
        )
        self.assertEqual(req.url, "https://ntfy.example.com/lifeos")
        self.assertEqual(req.data.decode(), "Due soon: Review quarterly report")
        self.assertEqual(req.headers["Title"], "Due soon")
        self.assertIn("lifeos", req.headers["Tags"])
        self.assertEqual(req.headers["Authorization"], "Bearer secret")

    def test_gotify_request_shape(self):
        req = build_webhook_request(
            channel="gotify",
            url="https://gotify.example.com",
            token="app-token",
            payload=self._payload(),
        )
        self.assertEqual(req.url, "https://gotify.example.com/message")
        body = json.loads(req.data.decode())
        self.assertEqual(body["title"], "Due soon")
        self.assertIn("Review quarterly report", body["message"])
        self.assertEqual(req.headers["X-Gotify-Key"], "app-token")

    def test_raw_json_request_shape(self):
        req = build_webhook_request(
            channel="raw_json",
            url="https://example.com/hook",
            token="tok",
            payload=self._payload(),
        )
        body = json.loads(req.data.decode())
        self.assertEqual(body["title"], "Review quarterly report")
        self.assertEqual(body["kind"], SystemEnums.ReminderKind.DUE_APPROACHING)
        self.assertEqual(body["item_id"], 42)
        self.assertEqual(req.headers["Authorization"], "Bearer tok")

    def test_dispatch_channel_name_defaults_ntfy(self):
        self.assertEqual(dispatch_channel_name("ntfy"), "webhook_ntfy")
        self.assertEqual(dispatch_channel_name("bogus"), "webhook_ntfy")

    @patch("lifeos_app.services.notify._execute_webhook_request")
    def test_deliver_webhook_uses_adapter(self, mock_execute):
        payload = self._payload()
        deliver_webhook(
            channel="ntfy",
            url="https://ntfy.example.com/topic",
            token="",
            payload=payload,
        )
        mock_execute.assert_called_once()
        request = mock_execute.call_args[0][0]
        self.assertEqual(request.data.decode(), "Due soon: Review quarterly report")

    @patch("lifeos_app.services.notify.deliver_webhook")
    def test_send_test_webhook_ntfy_message(self, mock_deliver):
        save_notification_settings(
            notifications_enabled=True,
            notification_channel="ntfy",
            notification_webhook_url="https://ntfy.example.com/lifeos",
            notification_webhook_token="",
            reminder_lead_minutes=15,
        )
        result = send_test_webhook()
        self.assertTrue(result.ok)
        self.assertIn("ntfy", result.message.lower())
        mock_deliver.assert_called_once()
        payload = mock_deliver.call_args.kwargs["payload"]
        self.assertEqual(payload.kind, "TEST")

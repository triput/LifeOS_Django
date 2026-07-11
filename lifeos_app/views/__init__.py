# ==============================================================================
# File: lifeos_app/views/__init__.py
# Description: View package exports for LifeOS V2 URL routing
# Component: Core / Views
# Version: 2.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Public view callables re-exported for URLConf convenience."""

from .alerts import alerts_ack_view, alerts_glyph_view, alerts_sheet_view, alerts_snooze_view
from .auth import login_view, logout_view, setup_owner_view
from .cmd import cmd_commit_view, cmd_preview_view
from .dock import dock_bar_view, dock_restore_view
from .drawer import (
    container_add_time_view,
    drawer_calendar_event_view,
    drawer_container_view,
    drawer_item_view,
    drawer_minimize_view,
    item_add_time_view,
)
from .focus import focus_complete_view, focus_pause_view, focus_start_view
from .home import (
    fragment_active_focus,
    fragment_horizon,
    home_view,
)
from .board import board_move_view, board_reorder_view, board_view
from .academy import academy_view
from .analytics import analytics_view
from .bulk import (
    bulk_commit_view,
    bulk_preview_view,
    bulk_template_csv_view,
    bulk_view,
)
from .overview import overview_view
from .saved_views import saved_view_go_view, saved_view_save_view
from .stability import stability_hud_view
from .inbox import inbox_triage_view, inbox_view
from .matrix import (
    container_patch_field_view,
    item_patch_field_view,
    items_bulk_view,
    matrix_children_view,
    matrix_item_subtasks_view,
    matrix_view,
)
from .calendar import (
    calendar_auth_view,
    calendar_microsoft_auth_view,
    calendar_microsoft_oauth_callback_view,
    calendar_microsoft_refresh_list_view,
    calendar_microsoft_sync_view,
    calendar_oauth_callback_view,
    calendar_refresh_list_view,
    calendar_status_view,
    calendar_sync_view,
    calendar_toggle_view,
    calendar_color_view,
)
from .calendar_grid import (
    plan_calendar_allocations_toggle_view,
    plan_calendar_display_toggle_view,
    plan_calendar_view,
)
from .plan import plan_view, schedule_run_view, today_clear_view, today_plan_view
from .telemetry import telemetry_hud_view
from .settings import (
    settings_appearance_reset_color_view,
    settings_appearance_save_view,
    settings_availability_create_view,
    settings_availability_delete_view,
    settings_availability_edit_view,
    settings_availability_update_view,
    settings_bands_reset_view,
    settings_geocode_view,
    settings_general_save_view,
    settings_google_oauth_save_view,
    settings_calendar_push_save_view,
    settings_microsoft_oauth_save_view,
    settings_notifications_save_view,
    settings_view,
    settings_webhook_test_view,
)

__all__ = [
    "login_view",
    "logout_view",
    "setup_owner_view",
    "home_view",
    "overview_view",
    "board_view",
    "board_move_view",
    "board_reorder_view",
    "academy_view",
    "analytics_view",
    "bulk_view",
    "bulk_template_csv_view",
    "bulk_preview_view",
    "bulk_commit_view",
    "saved_view_save_view",
    "saved_view_go_view",
    "fragment_active_focus",
    "fragment_horizon",
    "telemetry_hud_view",
    "stability_hud_view",
    "cmd_preview_view",
    "cmd_commit_view",
    "focus_start_view",
    "focus_pause_view",
    "focus_complete_view",
    "inbox_view",
    "inbox_triage_view",
    "matrix_view",
    "matrix_children_view",
    "matrix_item_subtasks_view",
    "item_patch_field_view",
    "container_patch_field_view",
    "items_bulk_view",
    "drawer_item_view",
    "drawer_calendar_event_view",
    "drawer_container_view",
    "drawer_minimize_view",
    "item_add_time_view",
    "container_add_time_view",
    "dock_bar_view",
    "dock_restore_view",
    "plan_view",
    "plan_calendar_view",
    "plan_calendar_display_toggle_view",
    "plan_calendar_allocations_toggle_view",
    "schedule_run_view",
    "today_plan_view",
    "today_clear_view",
    "calendar_auth_view",
    "calendar_microsoft_auth_view",
    "calendar_microsoft_oauth_callback_view",
    "calendar_microsoft_sync_view",
    "calendar_microsoft_refresh_list_view",
    "calendar_oauth_callback_view",
    "calendar_sync_view",
    "calendar_refresh_list_view",
    "calendar_toggle_view",
    "calendar_color_view",
    "calendar_status_view",
    "alerts_glyph_view",
    "alerts_sheet_view",
    "alerts_snooze_view",
    "alerts_ack_view",
    "settings_view",
    "settings_general_save_view",
    "settings_geocode_view",
    "settings_bands_reset_view",
    "settings_appearance_save_view",
    "settings_appearance_reset_color_view",
    "settings_notifications_save_view",
    "settings_webhook_test_view",
    "settings_google_oauth_save_view",
    "settings_calendar_push_save_view",
    "settings_microsoft_oauth_save_view",
    "settings_availability_create_view",
    "settings_availability_edit_view",
    "settings_availability_update_view",
    "settings_availability_delete_view",
]

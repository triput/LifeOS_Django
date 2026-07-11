# ==============================================================================
# File: lifeos_app/urls.py
# Description: Application URL routes for LifeOS V2 cockpit surfaces
# Component: Core / URL Configuration
# Version: 2.4 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-11
# ==============================================================================
"""App-level routes — P1 capture/focus, P2 matrix, P3 plan/schedule/alerts."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    # P1 — Command palette & focus
    path("cmd/preview/", views.cmd_preview_view, name="cmd-preview"),
    path("cmd/commit/", views.cmd_commit_view, name="cmd-commit"),
    path("focus/start/<int:item_id>/", views.focus_start_view, name="focus-start"),
    path("focus/pause/", views.focus_pause_view, name="focus-pause"),
    path("focus/complete/", views.focus_complete_view, name="focus-complete"),
    path("focus/complete/<int:item_id>/", views.focus_complete_view, name="focus-complete-item"),
    path("fragments/active-focus/", views.fragment_active_focus, name="fragment-active-focus"),
    path("fragments/horizon/", views.fragment_horizon, name="fragment-horizon"),
    path("telemetry/hud/", views.telemetry_hud_view, name="telemetry-hud"),
    path("stability/hud/", views.stability_hud_view, name="stability-hud"),
    # P1 — Inbox triage
    path("canvas/inbox/", views.inbox_view, name="canvas-inbox"),
    path("inbox/<int:item_id>/triage/", views.inbox_triage_view, name="inbox-triage"),
    # P2 — Matrix & drawer & dock
    path("canvas/matrix/", views.matrix_view, name="canvas-matrix"),
    path("matrix/children/<int:container_id>/", views.matrix_children_view, name="matrix-children"),
    path("matrix/subtasks/<int:item_id>/", views.matrix_item_subtasks_view, name="matrix-subtasks"),
    path("items/<int:item_id>/patch-field/", views.item_patch_field_view, name="item-patch-field"),
    path(
        "containers/<int:container_id>/patch-field/",
        views.container_patch_field_view,
        name="container-patch-field",
    ),
    path("items/bulk/", views.items_bulk_view, name="items-bulk"),
    path("drawers/item/<int:item_id>/", views.drawer_item_view, name="drawer-item"),
    path(
        "drawers/calendar-event/<int:event_id>/",
        views.drawer_calendar_event_view,
        name="drawer-calendar-event",
    ),
    path("drawers/container/<int:container_id>/", views.drawer_container_view, name="drawer-container"),
    path("drawers/minimize/", views.drawer_minimize_view, name="drawer-minimize"),
    path("items/<int:item_id>/add-time/", views.item_add_time_view, name="item-add-time"),
    path(
        "containers/<int:container_id>/add-time/",
        views.container_add_time_view,
        name="container-add-time",
    ),
    path("dock/", views.dock_bar_view, name="dock-bar"),
    path("dock/restore/<str:token>/", views.dock_restore_view, name="dock-restore"),
    # P3 — Plan, schedule, today, alerts
    path("canvas/plan/", views.plan_view, name="canvas-plan"),
    path("canvas/plan/calendar/", views.plan_calendar_view, name="canvas-plan-calendar"),
    path(
        "plan/calendar/<int:calendar_pk>/display/",
        views.plan_calendar_display_toggle_view,
        name="plan-calendar-display-toggle",
    ),
    path(
        "plan/calendar/allocations/",
        views.plan_calendar_allocations_toggle_view,
        name="plan-calendar-allocations-toggle",
    ),
    path("schedule/run/", views.schedule_run_view, name="schedule-run"),
    path("today/plan/", views.today_plan_view, name="today-plan"),
    path("today/clear/", views.today_clear_view, name="today-clear"),
    path("calendar/auth/", views.calendar_auth_view, name="calendar-auth"),
    path("calendar/oauth2callback/", views.calendar_oauth_callback_view, name="calendar-oauth-callback"),
    path("calendar/microsoft/auth/", views.calendar_microsoft_auth_view, name="calendar-microsoft-auth"),
    path(
        "calendar/microsoft/oauth2callback/",
        views.calendar_microsoft_oauth_callback_view,
        name="calendar-microsoft-oauth-callback",
    ),
    path("calendar/sync/", views.calendar_sync_view, name="calendar-sync"),
    path("calendar/microsoft/sync/", views.calendar_microsoft_sync_view, name="calendar-microsoft-sync"),
    path("calendar/refresh/", views.calendar_refresh_list_view, name="calendar-refresh"),
    path(
        "calendar/microsoft/refresh/",
        views.calendar_microsoft_refresh_list_view,
        name="calendar-microsoft-refresh",
    ),
    path("calendar/<int:calendar_pk>/toggle/", views.calendar_toggle_view, name="calendar-toggle"),
    path("calendar/<int:calendar_pk>/color/", views.calendar_color_view, name="calendar-color"),
    path("calendar/status/", views.calendar_status_view, name="calendar-status"),
    path("alerts/glyph/", views.alerts_glyph_view, name="alerts-glyph"),
    path("alerts/sheet/", views.alerts_sheet_view, name="alerts-sheet"),
    path("alerts/<int:dispatch_id>/snooze/", views.alerts_snooze_view, name="alerts-snooze"),
    path("alerts/<int:dispatch_id>/ack/", views.alerts_ack_view, name="alerts-ack"),
    # P3 — Settings
    path("canvas/settings/", views.settings_view, name="canvas-settings"),
    path("settings/general/", views.settings_general_save_view, name="settings-general-save"),
    path("settings/geocode/", views.settings_geocode_view, name="settings-geocode"),
    path("settings/bands/reset/", views.settings_bands_reset_view, name="settings-bands-reset"),
    path("settings/appearance/", views.settings_appearance_save_view, name="settings-appearance-save"),
    path(
        "settings/appearance/reset-color/",
        views.settings_appearance_reset_color_view,
        name="settings-appearance-reset-color",
    ),
    path(
        "settings/notifications/",
        views.settings_notifications_save_view,
        name="settings-notifications-save",
    ),
    path("settings/webhook-test/", views.settings_webhook_test_view, name="settings-webhook-test"),
    path("settings/google-oauth/", views.settings_google_oauth_save_view, name="settings-google-oauth-save"),
    path(
        "settings/calendar-push/",
        views.settings_calendar_push_save_view,
        name="settings-calendar-push-save",
    ),
    path(
        "settings/microsoft-oauth/",
        views.settings_microsoft_oauth_save_view,
        name="settings-microsoft-oauth-save",
    ),
    path(
        "settings/availability/",
        views.settings_availability_create_view,
        name="settings-availability-create",
    ),
    path(
        "settings/availability/<int:block_id>/edit/",
        views.settings_availability_edit_view,
        name="settings-availability-edit",
    ),
    path(
        "settings/availability/<int:block_id>/update/",
        views.settings_availability_update_view,
        name="settings-availability-update",
    ),
    path(
        "settings/availability/<int:block_id>/delete/",
        views.settings_availability_delete_view,
        name="settings-availability-delete",
    ),
    # P4 surfaces
    path("canvas/overview/", views.overview_view, name="canvas-overview"),
    path("canvas/board/", views.board_view, name="canvas-board"),
    path("canvas/board/move/", views.board_move_view, name="board-move"),
    path("canvas/board/reorder/", views.board_reorder_view, name="board-reorder"),
    path("canvas/academy/", views.academy_view, name="canvas-academy"),
    path("views/save/", views.saved_view_save_view, name="saved-view-save"),
    path("views/go/<slug:slug>/", views.saved_view_go_view, name="saved-view-go"),
    path("canvas/analytics/", views.analytics_view, name="canvas-analytics"),
    # P5 — Bulk add (BL-BULK-001)
    path("canvas/bulk/", views.bulk_view, name="canvas-bulk"),
    path("bulk/template.csv", views.bulk_template_csv_view, name="bulk-template-csv"),
    path("bulk/preview/", views.bulk_preview_view, name="bulk-preview"),
    path("bulk/commit/", views.bulk_commit_view, name="bulk-commit"),
]

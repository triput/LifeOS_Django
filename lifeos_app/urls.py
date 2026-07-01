 # ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/urls.py
# Description: Application level URL routing configurations for Django endpoints
# Component: Core / URL Configuration
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-07-01
# ==============================================================================
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('api/task-action/', views.task_action_view, name='task-action'),
    path('toggle-task/<int:task_id>/', views.toggle_task, name='toggle_task'),
    path('container/<int:container_id>/', views.container_detail_view, name='container_detail'),
    
    # V2.0 Routes
    path('quick-entry/', views.quick_entry_view, name='quick-entry'),
    path('clear-toast/', views.clear_toast_view, name='clear-toast'),
    path('triage/', views.triage_view, name='triage'),
    path('triage/<int:item_id>/process/', views.process_triage_view, name='process-triage'),
    path('triage/container/<int:container_id>/process/', views.process_container_triage_view, name='process-container-triage'),
    
    # V4.0 Planner Routes
    path('planner/', views.planner_view, name='planner'),
    path('planner/parse-nl/', views.planner_parse_nl_view, name='planner-parse-nl'),
    path('planner/toggle-blocking/<int:event_id>/', views.planner_toggle_blocking_view, name='planner-toggle-blocking'),
    
    path('settings/', views.settings_view, name='settings'),
    path('settings/backup/', views.backup_view, name='backup'),
    path('settings/domain/add/', views.domain_add_view, name='domain-add'),
    path('settings/domain/delete/<int:domain_id>/', views.domain_delete_view, name='domain-delete'),
    path('settings/users/', views.user_management_view, name='user-management'),
    path('settings/users/delete/<int:user_id>/', views.delete_user_view, name='delete-user'),
    path('settings/container/check-bounds/<int:container_id>/', views.container_check_bounds_view, name='container-check-bounds'),
    
    # Calendar OAuth Endpoints
    path('settings/calendar/add/', views.calendar_add_view, name='calendar-add'),
    path('settings/calendar/delete/<int:cal_id>/', views.calendar_delete_view, name='calendar-delete'),
    path('settings/calendar/toggle/<int:cal_id>/', views.calendar_toggle_active_view, name='calendar-toggle-active'),
    path('settings/calendar/auth/', views.calendar_auth_view, name='calendar-auth'),
    path('settings/calendar/oauth2callback/', views.calendar_oauth2callback_view, name='calendar-oauth2callback'),
    
    path('explorer/', views.explorer_view, name='explorer'),
    path('explorer/children/', views.explorer_children_view, name='explorer-children'),
    path('explorer/add-child/', views.explorer_add_child_view, name='explorer-add-child'),
    path('explorer/move/', views.explorer_move_view, name='explorer-move'),
    path('explorer/edit/<str:node_type>/<int:node_id>/', views.explorer_edit_view, name='explorer-edit'),
    path('explorer/bulk-action/', views.explorer_bulk_action_view, name='explorer-bulk-action'),
    
    # V5.1 Backlog Grid Editor Routes
    path('explorer/grid/', views.explorer_grid_view, name='explorer-grid'),
    path('explorer/grid/children/', views.explorer_grid_children_view, name='explorer-grid-children'),
    path('explorer/grid/save-field/', views.explorer_grid_save_field_view, name='explorer-grid-save-field'),
    path('explorer/grid/add-row/', views.explorer_grid_add_row_view, name='explorer-grid-add-row'),
    path('explorer/grid/create-tag/', views.explorer_grid_create_tag_view, name='explorer-grid-create-tag'),
    path('explorer/grid/modal/<str:model_type>/<int:model_id>/', views.explorer_grid_modal_view, name='explorer-grid-modal'),
    path('explorer/grid/bulk-action/', views.explorer_grid_bulk_action_view, name='explorer-grid-bulk-action'),
    path('explorer/grid/bulk-save/', views.explorer_grid_bulk_save_view, name='explorer-grid-bulk-save'),
    
    path('analytics/', views.analytics_view, name='analytics'),
    path('analytics/drilldown/', views.analytics_drilldown_view, name='analytics-drilldown'),
    path('toggle-pin/<int:item_id>/', views.toggle_pin_view, name='toggle-pin'),
    path('academy/', views.academy_view, name='academy'),
    path('academy/certification/add/', views.certification_add_view, name='certification-add'),
    path('academy/certification/delete/<int:cert_id>/', views.certification_delete_view, name='certification-delete'),
    
    # Tag Scoping and Management (Phase 4)
    path('settings/tags/', views.tags_manager_view, name='tags-manager'),
    path('settings/tag/add/', views.tag_add_view, name='tag-add'),
    path('settings/tag/edit/<int:tag_id>/', views.tag_edit_view, name='tag-edit'),
    path('settings/tag/delete/<int:tag_id>/', views.tag_delete_view, name='tag-delete'),
    path('settings/tag/retag/<int:tag_id>/', views.tag_retag_view, name='tag-retag'),
    
    # Kanban Views
    path('kanban/status/', views.kanban_status_view, name='kanban-status'),
    path('kanban/priority/', views.kanban_priority_view, name='kanban-priority'),
    path('kanban/move/', views.kanban_move_view, name='kanban-move'),
    
    # Roadmap & Agenda
    path('roadmap/', views.roadmap_view, name='roadmap'),
    path('agenda/', views.agenda_view, name='agenda'),
]


# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/urls.py
# Description: Application level URL routing configurations for Django endpoints
# Component: Core / URL Configuration
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
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
    
    # V4.0 Planner Routes
    path('planner/', views.planner_view, name='planner'),
    path('planner/parse-nl/', views.planner_parse_nl_view, name='planner-parse-nl'),
    path('planner/toggle-blocking/<int:event_id>/', views.planner_toggle_blocking_view, name='planner-toggle-blocking'),
    
    path('settings/', views.settings_view, name='settings'),
    path('settings/backup/', views.backup_view, name='backup'),
    path('settings/domain/add/', views.domain_add_view, name='domain-add'),
    path('settings/domain/delete/<int:domain_id>/', views.domain_delete_view, name='domain-delete'),
    path('settings/calendar/add/', views.calendar_add_view, name='calendar-add'),
    path('settings/calendar/delete/<int:cal_id>/', views.calendar_delete_view, name='calendar-delete'),
    path('explorer/', views.explorer_view, name='explorer'),
    path('explorer/children/', views.explorer_children_view, name='explorer-children'),
    path('explorer/add-child/', views.explorer_add_child_view, name='explorer-add-child'),
    path('explorer/move/', views.explorer_move_view, name='explorer-move'),
    path('explorer/edit/<str:node_type>/<int:node_id>/', views.explorer_edit_view, name='explorer-edit'),
    path('explorer/bulk-action/', views.explorer_bulk_action_view, name='explorer-bulk-action'),
    path('analytics/', views.analytics_view, name='analytics'),
    path('analytics/drilldown/', views.analytics_drilldown_view, name='analytics-drilldown'),
    path('toggle-pin/<int:item_id>/', views.toggle_pin_view, name='toggle-pin'),
    path('academy/', views.academy_view, name='academy'),
    path('academy/certification/add/', views.certification_add_view, name='certification-add'),
    path('academy/certification/delete/<int:cert_id>/', views.certification_delete_view, name='certification-delete'),
]


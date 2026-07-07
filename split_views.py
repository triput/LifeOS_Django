import ast
import os

VIEWS_DIR = 'd:\\CodeRepo\\LifeOS\\lifeos_app\\views'
VIEWS_FILE = 'd:\\CodeRepo\\LifeOS\\lifeos_app\\views.py'

# Groupings
MODULES = {
    'auth.py': ['login_view', 'logout_view', 'user_management_view', 'delete_user_view'],
    'dashboard.py': ['dashboard_view', 'quick_entry_view', 'clear_toast_view', 'triage_view', 'process_triage_view', 'process_container_triage_view', 'container_detail_view', 'toggle_task', 'task_action_view', 'toggle_pin_view'],
    'settings.py': ['settings_view', 'domain_add_view', 'domain_delete_view', 'calendar_add_view', 'calendar_delete_view', 'calendar_toggle_active_view', 'tags_manager_view', 'tag_add_view', 'tag_edit_view', 'tag_delete_view', 'tag_retag_view', 'backup_view'],
    'explorer.py': ['explorer_view', 'explorer_children_view', 'explorer_add_child_view', 'explorer_move_view', 'explorer_edit_view', 'explorer_bulk_action_view', '_cascade_container_dates', '_cascade_item_dates', 'parse_datetime_input_tz', 'container_check_bounds_view', '_get_recursive_children_containers_and_items', '_get_recursive_subtasks_for_item'],
    'grid.py': ['explorer_grid_view', 'explorer_grid_children_view', 'explorer_grid_save_field_view', 'explorer_grid_add_row_view', 'explorer_grid_create_tag_view', 'explorer_grid_modal_view', 'explorer_grid_bulk_action_view', 'explorer_grid_bulk_save_view'],
    'analytics.py': ['analytics_view', 'analytics_drilldown_view'],
    'academy.py': ['academy_view', 'certification_add_view', 'certification_delete_view'],
    'planner.py': ['planner_view', 'planner_parse_nl_view', 'planner_toggle_blocking_view', 'calendar_auth_view', 'calendar_oauth2callback_view'],
    'kanban.py': ['kanban_status_view', 'kanban_priority_view', 'kanban_move_view', 'roadmap_view', 'agenda_view']
}

def main():
    if not os.path.exists(VIEWS_DIR):
        os.makedirs(VIEWS_DIR)
        
    with open(VIEWS_FILE, 'r', encoding='utf-8') as f:
        source = f.read()
        
    lines = source.splitlines()
    tree = ast.parse(source)
    
    # Extract imports (assume anything before the first function definition is header/imports)
    first_func_line = min(node.lineno for node in tree.body if isinstance(node, ast.FunctionDef))
    
    header_lines = lines[:first_func_line - 1]
    
    # For every function, extract its code
    func_code = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            start = node.lineno - 1
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            end = node.end_lineno
            func_code[node.name] = "\n".join(lines[start:end])
            
    # Write each module
    for mod_name, funcs in MODULES.items():
        mod_path = os.path.join(VIEWS_DIR, mod_name)
        with open(mod_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(header_lines) + "\n\n")
            for func in funcs:
                if func in func_code:
                    f.write(func_code[func] + "\n\n")
                else:
                    print(f"WARNING: Function {func} not found in views.py")
                    
    # Write __init__.py
    with open(os.path.join(VIEWS_DIR, '__init__.py'), 'w', encoding='utf-8') as f:
        for mod_name in MODULES.keys():
            mod_base = mod_name.replace('.py', '')
            f.write(f"from .{mod_base} import *\n")

if __name__ == '__main__':
    main()

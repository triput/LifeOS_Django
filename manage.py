# ==============================================================================
# File: manage.py
# Description: Django command-line utility for administrative tasks
# Component: Core / Management Entry Point
# Version: 1.0 (Gold Master)
# Created: 2026-06-30
# Last Update: 2026-06-30
# ==============================================================================
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

# Swap standard sqlite3 with pysqlite3-binary if installed (common on shared hosting)
try:
    import pysqlite3
    import pysqlite3.dbapi2
    
    # Ensure SQLITE_LIMIT_VARIABLE_NUMBER is defined on both namespaces
    for mod in (pysqlite3, pysqlite3.dbapi2):
        if not hasattr(mod, 'SQLITE_LIMIT_VARIABLE_NUMBER'):
            mod.SQLITE_LIMIT_VARIABLE_NUMBER = 9
            
    # Patch Connection to support getlimit
    if not hasattr(pysqlite3.dbapi2.Connection, 'getlimit'):
        class PatchedConnection(pysqlite3.dbapi2.Connection):
            def getlimit(self, limit):
                return 999
        
        # Keep reference to the original Connection
        org_Connection = pysqlite3.dbapi2.Connection
        
        # Override the Connection class in both namespaces
        pysqlite3.Connection = PatchedConnection
        pysqlite3.dbapi2.Connection = PatchedConnection
        
        # Override connect in both namespaces to inject PatchedConnection factory
        org_connect = pysqlite3.dbapi2.connect
        def patched_connect(*args, **kwargs):
            factory = kwargs.get('factory')
            if factory is None or factory == org_Connection:
                kwargs['factory'] = PatchedConnection
            return org_connect(*args, **kwargs)
            
        pysqlite3.connect = patched_connect
        pysqlite3.dbapi2.connect = patched_connect
        
    sys.modules['sqlite3'] = pysqlite3
    sys.modules['sqlite3.dbapi2'] = pysqlite3.dbapi2
except ImportError:
    pass


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lifeos_django.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()


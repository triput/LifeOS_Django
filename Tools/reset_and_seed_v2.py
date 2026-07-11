"""One-shot: drop all public tables then migrate + seed (disposable test DB)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lifeos_django.settings")
django.setup()

from django.core.management import call_command
from django.db import connection

sql = """
DO $$ DECLARE r RECORD;
BEGIN
  FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
    EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
  END LOOP;
END $$;
"""

with connection.cursor() as c:
    c.execute(sql)
print("dropped all public tables")
call_command("migrate", verbosity=1)
call_command(
    "seed_data",
    flush=True,
    username="owner",
    password="ownerpass",
    verbosity=1,
)
print("migrate + seed complete")

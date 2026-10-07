"""
Logical backups of this app's own tables (everything in Postgres `public`) and
a selective, Renova-focused restore — see scripts/backup_db.py and
scripts/restore_renova.py. Supabase Auth (`auth.users`) is not ours to copy:
an advisor signs in again with the same account; their `users` row (and
everything that points at it) is what lives here.
"""

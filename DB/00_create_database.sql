-- Create the unified attendance database (PostgreSQL 18 + pgvector).
--
--   psql -U postgres -f DB/00_create_database.sql
--   psql -U postgres -d srm_attendance -f DB/init_postgresql.sql
--
-- Leaves the existing `SRM_Attendance` database alone.

SELECT 'CREATE DATABASE srm_attendance WITH ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'srm_attendance')\gexec

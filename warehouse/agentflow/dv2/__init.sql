DROP DATABASE IF EXISTS rv;
CREATE DATABASE IF NOT EXISTS rv;

-- Include order for orchestration tools:
-- INCLUDE raw_vault/hubs/*.sql
-- INCLUDE raw_vault/links/*.sql
-- INCLUDE raw_vault/satellites/*.sql

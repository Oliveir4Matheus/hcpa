-- Plataforma HCPA — inicialização do Postgres
-- Executado uma vez na primeira subida do container (docker-entrypoint-initdb.d).
-- Migrations subsequentes são gerenciadas pelo Alembic.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;

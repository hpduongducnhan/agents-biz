-- Chạy 1 lần khi volume Postgres mới: DB dev (tạo sẵn bởi POSTGRES_DB) + test + stack thử, extension dùng chung.
CREATE DATABASE "bizwithagents_test" OWNER bizwithagents;
CREATE DATABASE "bizwithagents_e2e" OWNER bizwithagents;
\connect bizwithagents
CREATE EXTENSION IF NOT EXISTS citext;
\connect "bizwithagents_test"
CREATE EXTENSION IF NOT EXISTS citext;
\connect "bizwithagents_e2e"
CREATE EXTENSION IF NOT EXISTS citext;

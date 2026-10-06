-- Exécuté une seule fois, à l'initialisation du volume PostgreSQL.
-- La base principale est créée par POSTGRES_DB ; celle de test ne l'est pas,
-- et pytest en a besoin.
CREATE DATABASE finance_auth_test OWNER finance;

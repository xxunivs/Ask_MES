-- 백엔드가 쓰는 읽기 전용 계정 (SELECT 만 가능)
-- 실행: sqlcmd -v READER_PASSWORD="..." -i 02_create_reader.sql
USE MES_DEMO;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'mes_reader')
    CREATE LOGIN mes_reader WITH PASSWORD = '$(READER_PASSWORD)', DEFAULT_DATABASE = MES_DEMO;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'mes_reader')
    CREATE USER mes_reader FOR LOGIN mes_reader;
GO
ALTER ROLE db_datareader ADD MEMBER mes_reader;
GO

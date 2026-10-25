# 가상 데이터 생성

실제 공장 데이터는 공개할 수 없어서, 실제 DB의 값 모양만 조사해 같은 모양의 가상 데이터를 만든다.

1. `profile_real_db.py`: 실제 DB에서 컬럼별 빈 값 비율, 코드값, ID 모양 조사 -> `real_db_profile.json` (실제 기록 없음)
2. `generate_demo_data.py`: `real_db_profile.json`과 `fake_vocab.py`로 가짜 데이터 생성 -> 데모 SQL Server
3. `export_sqlite.py`: 데모 SQL Server -> `backend/data/mes_demo.sqlite` (공개 데모가 쓰는 DB)

데모 SQL Server는 이 폴더의 `docker-compose.yml`로 띄우고, `01_create_tables.sql`(테이블 26개), `02_create_reader.sql`(조회 전용 계정) 순서로 실행한다.

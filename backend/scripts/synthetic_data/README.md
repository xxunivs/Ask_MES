# 가상 데이터 생성

공개 데모(ask-mes.web.app)가 쓰는 데이터를 만드는 폴더입니다.

1. `profile_real_db.py`: 실제 DB의 값 모양 조사 → `real_db_profile.json` (실제 값 없음)
2. `generate_demo_data.py`: 그 모양대로 가짜 데이터 생성 → 데모 SQL Server (`docker-compose.yml`)
3. `export_sqlite.py`: SQLite 파일로 내보내기 → `backend/data/mes_demo.sqlite`

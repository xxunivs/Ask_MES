# 가상 데이터 생성

공개 데모(ask-mes.web.app)가 쓰는 데이터를 만드는 폴더입니다.

실제 공장 MES 데이터는 회사 정보라 공개할 수 없습니다. 그래서 실제 DB에서는 값의 생김새(빈 값 비율, 코드값 종류, ID 형식)만 조사하고, 그 모양에 맞춰 가짜 값을 새로 만들었습니다. 테이블과 컬럼 구조는 실제 DB와 같고, 들어 있는 값은 모두 가짜입니다. (테이블 26개, 약 2만 9천 행)

## 만드는 순서

```
실제 DB ──① 모양 조사──▶ real_db_profile.json ──② 가짜 값 생성──▶ 데모 SQL Server ──③ 내보내기──▶ mes_demo.sqlite
```

### 1. 실제 DB의 값 모양 조사 (`profile_real_db.py`)

실제 DB에서 2,000행씩 뽑아 컬럼마다 빈 값 비율, 코드값 목록, ID 형식을 기록합니다. ID는 `AAA_99999999_9999`처럼 글자 종류만 남기고, 사람 이름이나 자유 서술 컬럼은 값을 보관하지 않습니다.

결과: `real_db_profile.json` (실제 기록 없음)

### 2. 가짜 데이터 생성 (`generate_demo_data.py`, `fake_vocab.py`)

조사한 모양대로 값을 만들어 데모 SQL Server에 넣습니다. 설비명, 제품명 같은 이름은 실제 회사 값이 아닌 일반 용어(`fake_vocab.py`)로 채웁니다.

### 3. SQLite로 내보내기 (`export_sqlite.py`)

데모 SQL Server의 데이터를 파일 하나짜리 DB로 옮깁니다. 배포판은 별도 DB 서버 없이 이 파일(`backend/data/mes_demo.sqlite`)을 읽습니다.

## 데모 SQL Server 띄우기

| 파일 | 역할 |
|------|------|
| `docker-compose.yml` | SQL Server 컨테이너 실행 (`.env.example`을 `.env`로 복사해 비밀번호 입력) |
| `01_create_tables.sql` | 실제 DB와 같은 구조의 테이블 26개 생성 |
| `02_create_reader.sql` | 백엔드가 쓰는 조회 전용 계정 생성 |

모든 스크립트는 `backend/` 폴더에서 실행합니다.

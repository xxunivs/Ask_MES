"""
가상 데이터용 절삭공구 제조 업종 어휘 (일반 용어, 실제 회사 값 아님)
표별 ID 형식, 이름 목록, 칸별 값 목록
"""
from __future__ import annotations

# 표 자신의 ID 형식, {n} 은 1부터 시작하는 번호
ID_FORMATS = {
    "CIM_CODECLASS": "CC{n:03d}",
    "CIM_CODE": "CD{n:04d}",
    "CIM_FACILITY": "FAC-{n:02d}",
    "CIM_EQUIPMENTCLASS": "EQC-{n:02d}",
    "CIM_EQUIPMENT": "EQ-{n:04d}",
    "CIM_PRODUCTCLASS": "PC{n:02d}",
    "CIM_PRODUCTDEFINITION": "{n:08d}",
    "CIM_PROCESSDEFINITION": "PD-{n:02d}",
    "CIM_PROCESSSEGMENT": "SEG{n:03d}",
    "CIM_PROCESSNODE": "PN-{n:04d}",
    "CIM_MATERIALCLASS": "MC{n:02d}",
    "CIM_MATERIALDEFINITION": "61-{n:03d}-{n2:04d}",
    "CIM_MATERIALLOT": "ML{n:08d}",
    "CIM_DEFECTCLASS": "DC{n:02d}",
    "CIM_DEFECT": "DF{n:03d}",
    "CIM_PRODUCTORDER": "{n:08d}",
    "CIM_LOT": "{n:08d}-10",
    "CIM_BATCH": "BAT-{n:05d}",
}
# 실제 ID 처럼 보이도록 큰 수에서 시작하는 번호
ID_OFFSETS = {"CIM_PRODUCTDEFINITION": 22000000, "CIM_PRODUCTORDER": 33000000, "CIM_LOT": 82600000, "CIM_MATERIALLOT": 45000000}

PROCESS_SEGMENTS = ["절단", "센터리스 연삭", "열처리", "외경 연삭", "날 연삭", "홈 가공", "호닝", "세척", "PVD 코팅",
                    "레이저 마킹", "중간 검사", "최종 검사", "포장", "출하 대기"]
PROCESS_DEFINITIONS = ["엔드밀 표준 공정", "볼 엔드밀 공정", "드릴 표준 공정", "롱 드릴 공정", "탭 표준 공정",
                       "리머 공정", "인서트 공정", "재연삭 공정", "코팅 재작업 공정", "샘플 공정"]
EQUIPMENT_CLASSES = ["CNC 공구연삭기", "외경 연삭기", "센터리스 연삭기", "절단기", "진공 열처리로", "PVD 코팅기",
                     "세척기", "레이저 마킹기", "측정기", "포장기", "호닝기", "로더"]
FACILITIES = ["가공동 1층", "가공동 2층", "열처리동", "코팅동", "세척실", "검사실", "포장실", "원자재 창고",
              "반제품 창고", "완제품 창고", "출하장", "공구실", "QC 실험실", "설비 보전실", "외주 대기장",
              "가공동 3층", "레이저실", "재연삭실", "샘플실", "자동화 라인"]
PRODUCT_CLASSES = [("FERT", "완제품"), ("HALB", "반제품"), ("ROH", "원자재"), ("HIBE", "소모품"), ("VERP", "포장재"),
                   ("DIEN", "서비스"), ("UNBW", "비평가 자재"), ("NLAG", "비재고 자재"), ("ERSA", "예비품"), ("FHMI", "생산 보조")]
PRODUCT_SHAPES = ["{f}F SQ END MILL D{d}", "{f}F BALL END MILL R{r}", "{f}F CORNER R END MILL D{d}",
                  "CARBIDE DRILL D{d}", "HSS DRILL D{d}", "LONG DRILL D{d}", "SPIRAL TAP M{m}", "POINT TAP M{m}",
                  "REAMER D{d}", "ROUGHING END MILL D{d}"]
MATERIAL_CLASSES = ["초경 환봉", "HSS 환봉", "코팅 타겟", "연마 휠", "포장 케이스", "라벨", "절삭유", "세척제", "열처리 가스", "소모성 공구"]
MATERIAL_SHAPES = ["CARBIDE ROD CO10% D{d}x330", "CARBIDE ROD CO12% D{d}x330", "HSS PM ROUND BAR {d}MM",
                   "HSS M42 ROUND BAR {d}MM", "DIAMOND WHEEL D150", "CBN WHEEL D200", "TiAlN TARGET", "AlCrN TARGET",
                   "PLASTIC CASE {d}MM", "LABEL 40x20"]
DEFECT_CLASSES = ["가공 불량", "외관 불량", "치수 불량", "코팅 불량", "열처리 불량", "자재 불량", "마킹 불량", "포장 불량", "설비 이상", "기타"]
DEFECTS = ["날 치핑", "버 발생", "외경 치수 불량", "전장 불량", "진원도 불량", "표면 스크래치", "코팅 박리", "코팅 색상 불량",
           "경도 미달", "변형", "균열", "원자재 기공", "마킹 누락", "마킹 위치 불량", "포장 수량 오류", "라벨 오부착",
           "연삭 탐", "날 각도 불량", "홈 깊이 불량", "섕크 흠집"]
CODE_CLASSES = ["LOT 상태", "공정 상태", "설비 상태", "불량 유형", "단위", "자재 유형", "출고 구분", "입고 구분",
                "재작업 사유", "홀드 사유", "품질 등급", "포장 단위", "창고 구분", "작업 구분", "검사 유형",
                "코팅 종류", "열처리 조건", "우선순위", "고객 등급", "출하 방식"]
CUSTOMERS = ["Alpha Tools Co.", "Beta Machining Ltd.", "Gamma Precision", "Delta Industrial", "Epsilon Cutting Inc.",
             "Zeta Components", "Eta Motors", "Theta Aerospace", "Iota Molds", "Kappa Auto Parts"]

# 칸 이름별 값 목록 (표 공통)
LOT_ACTIVITIES = ["Create", "TrackIn", "TrackOut", "Hold", "Release", "Split", "Merge", "Ship"]
MASTER_ACTIVITIES = ["Create", "Modify"]
USERS = [f"user{i:02d}" for i in range(1, 21)]
COMMENTS = ["정기 점검 후 재가동", "샘플 출하 건", "고객 요청 긴급", "재작업 후 재검사", "코팅 두께 확인 필요",
            "설비 교체 후 첫 LOT", "수량 조정", "검사 결과 양호"]

# 불량 이름 포함 단어별 불량 분류
DEFECT_CLASS_RULES = [
    ("코팅", "코팅 불량"), ("경도", "열처리 불량"), ("원자재", "자재 불량"), ("마킹", "마킹 불량"),
    ("포장", "포장 불량"), ("라벨", "포장 불량"), ("스크래치", "외관 불량"), ("흠집", "외관 불량"),
    ("변형", "외관 불량"), ("균열", "외관 불량"), ("치수", "치수 불량"), ("전장", "치수 불량"),
    ("진원도", "치수 불량"), ("깊이", "치수 불량"), ("각도", "치수 불량"),
]

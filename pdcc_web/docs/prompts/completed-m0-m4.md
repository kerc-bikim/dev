# 완료된 M0–M4 (다시 구현하지 말 것)

번호 티켓 M0-01~M4-10과 관리자 화면 1.3–1.5·M2-07 강제 해제는 코드에 있습니다. 새 작업은 회귀 수정이나 명시된 다음 범위만 합니다.

## M0 뼈대·계정

- 모노레포 골격, compose(web/api/postgres/redis), `/health`
- 스텁 로그인 `stub`/`stub`, `stub2`/`stub2`, `DEV_BOOTSTRAP_ADMIN`의 `admin`
- 기관·사용자·역할, 프로젝트 멤버, 조회자 읽기 전용
- StationXML 1.2 가져오기 (원문 보관)

ADR: 0001, 0011, 0014

## M1 NRL

- 서버 프록시 catalog / prefix / combine / curve
- 고유값 2개 이상만 질문, 기준 모델 CMG-3T · Q330HR
- Redis 캐시, 장애 시 캐시 사용 배지
- 검색, 별칭, 제외 장비(Certimus 등)
- 관리자 연결 테스트, 카탈로그 새로고침, 모드, 전체 zip 오프라인

ADR: 0003, 0009, 0012, 0021, 0026

## M2 위저드·공동 작업

- 7단계 관측소 위저드, 채널 방위각·경사 규칙
- epoch 잠금·heartbeat, 관리자 강제 해제(사유, 초안 유지, 알림)
- 장비 세트, 버전, 실행 취소, 초안 머지
- 채널 폼, 좌표 하위 반영, 즉시 검사 패널
- 관측소 엑셀 복제

ADR: 0004, 0007, 0008, 0013, 0026

## M3 변환·검증·큐

- dataless SEED / RESP 가져오기 (JAR 또는 ObsPy)
- 공식 validator (JAR 또는 Python 번호), `_unvalidated` XML
- 대량 검증 작업 큐, 진행률, 재시도, 대기 취소
- SEED 손실 확인 후 내보내기, RESP/RESP zip
- 워커 `python -m app.jobs.runner`

ADR: 0010, 0015, 0016, 0017, 0018, 0019

## M4 운영

- 관리자 대시보드, 빨간 배지, 운영 알림(5xx·NRL 연속 실패·실패 작업·디스크)
- 백업 성공 시각 표식, `infra/backup-postgres.sh`, `docs/restore.md`
- 감사 로그 (NRL instconfig 포함)
- 프로젝트 보관·관리자 복원
- 업로드·NRL zip 경로/크기 검증
- 인앱 사용자 매뉴얼 `/help`, 관리자 매뉴얼 `/help/admin`
- 작업 목록·실패 로그, 시스템 한도·인용
- 현재 잠금 목록 (`GET /api/admin/locks`) — 기본 TTL 5분은 10분+ 대시보드에 안 나옴

ADR: 0020, 0022, 0023, 0024, 0025, 0026

## 의도적으로 없는 것

- 인벤토리 zip / MiniSEED / full SEED 가져오기
- compose에 worker 서비스 (운영에서 별도 프로세스로 실행)
- `infra/jars/`에 validator·converter JAR 동봉 (경로 환경 변수만)
- ADR 0002, 0005, 0006 번호 — 이 트리에 파일이 없습니다

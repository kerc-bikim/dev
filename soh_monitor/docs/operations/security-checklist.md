# 보안 점검표

발견 항목은 조치하거나 이 표에 위험을 수용한 이유를 적는다.

| 항목 | 상태 | 근거 |
|------|------|------|
| Secret 이 Git 에 없음 | 조치됨 | `scripts/check_secrets.py`, 예시만 `*.example` |
| Secret 이 이미지에 없음 | 조치됨 | Compose `*_FILE` / Docker Secret. 환경변수 평문 비밀번호 컬럼 없음 |
| 화면·로그에 비밀번호 없음 | 조치됨 | `credentialReference` 만 저장. Adapter `redact` |
| 세션 쿠키 HMAC | 조치됨 | `soh_session`, 역할 ADMIN/OPERATOR/VIEWER |
| VIEWER 는 설정·등록 숨김 | 조치됨 | Frontend `can("administer")` |
| 연결 시험·접속 저장 SSRF | 조치됨 | RFC1918 허용 목록, 메타데이터 주소 거부. PUT/POST 호스트에도 적용 |
| CSV 수식 주입·URI·SSRF | 조치됨 | 수식 거부. dataSourceUri 스킴·호스트 허용 대역은 PUT 과 같음 |
| Edge 는 Outbound 만 | 조치됨 | 중앙 Inbound 없음. Health 는 127.0.0.1 |
| mTLS 폐기 | 조치됨 | `POST /edges/{id}/revoke` → 403 |
| Postgres·Influx 포트 비공개 | 조치됨 | `compose.central.yml` data-net |
| 초기 관리자 비밀번호 변경 강제 | 조치됨 | `must_change_password` |
| TLS 종료 | 수용 | nginx 443. 개발 Compose 는 HTTP. 운영 `certs/` 필수 |

## 수용한 위험

- **개발 Compose 익명 Grafana Viewer.** 운영은 `GF_AUTH_ANONYMOUS_ENABLED` 를 끄고 관리자 비밀번호를 Secret 으로 준다.
- **개발 HMAC Edge 토큰.** 운영에서 nginx `ssl_verify_client` 를 켠다. [`edge-deployment/README.md`](../edge-deployment/README.md).

## 비밀 순환

1. 금고에 새 값을 만든다.
2. `secrets/` 파일을 교체한다.
3. 해당 서비스만 재기동한다. `session_secret` 은 전원 로그아웃을 뜻한다.
4. 이전 값은 금고에서 폐기 표시를 한다.

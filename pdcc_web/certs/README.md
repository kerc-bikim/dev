# 사내 SSL 가시화 인증서

내부망 SSL 검사 장비를 거치면 NRL 호출이 `CERTIFICATE_VERIFY_FAILED` 로 실패합니다.
보안팀이 준 PEM 인증서(예: `ABC.crt`)를 이 폴더에 두고 환경 변수를 지정하세요.

```bash
# pdcc_web/infra/.env 또는 호스트 환경
SSL_CA_BUNDLE=/certs/ABC.crt
```

compose 는 이 디렉터리를 컨테이너의 `/certs` 로 읽기 전용 마운트합니다.
호스트에서 API만 띄울 때는 파일 절대경로를 적습니다.

```bash
SSL_CA_BUNDLE=/path/to/ABC.crt
```

`.crt` 가 DER(바이너리)이면 PEM으로 변환합니다.

```bash
openssl x509 -inform der -in ABC.crt -out ABC.pem
```

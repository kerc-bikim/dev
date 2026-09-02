# ADR 0025. 업로드와 NRL zip 경계 검증

상태: 채택  
코드: `apps/api/app/inventory/importers.py`, `apps/api/app/routers/projects.py`,
`apps/api/app/nrl/offline.py`

## 결정

1. 프로젝트 가져오기는 `.xml`, `.seed`, `.dataless`, `.resp`와 표준 `RESP.*`
   파일명만 허용한다. 대소문자는 구분하지 않으며 경로 구분자, 드라이브 문자, NUL이
   포함된 파일명은 거부한다.
2. multipart 파일은 `MAX_UPLOAD_BYTES + 1`까지만 메모리로 읽는다. 제한 초과는
   HTTP 413으로 반환하며 프로젝트나 원본 자산을 만들지 않는다.
3. NRL zip은 다운로드 도중 `MAX_ZIP_BYTES`를 검사한다. 서버의
   `Content-Length`를 먼저 확인하되, 이 값이 없거나 틀린 경우에도 실제 수신 바이트를
   세어 같은 제한을 적용한다.
4. zip을 사용하기 전에 절대 경로, `..`, 역슬래시, Windows 드라이브 경로, NUL,
   중복 항목과 심볼릭 링크를 거부한다. archive 항목 수와 전체 압축 해제 크기도 각각
   `MAX_ZIP_MEMBERS`, `MAX_ZIP_UNCOMPRESSED_BYTES`로 제한한다.
5. 검증이 끝나기 전에는 임시 zip을 운영 경로로 교체하지 않는다. 실패한 임시 파일은
   삭제하고 기존 정상 archive는 보존한다.

통과: **M4-07** 허용되지 않은 확장자, 과대 파일·zip, 경로 탈출 zip을 서버 경계에서
차단한다.

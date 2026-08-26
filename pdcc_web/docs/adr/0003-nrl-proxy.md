# ADR 0003. NRL v2는 서버 프록시만

상태: 채택  
코드: `apps/api/app/nrl/`, `apps/api/app/routers/nrl.py`

## 결정

1. 브라우저는 EarthScope NRL (`https://service.earthscope.org/irisws/nrl/1/`)에 직접 호출하지 않는다.
2. API만 `/catalog`, `/prefix-lookup`, `/combine`을 호출한다. 기동 시 NRL을 치지 않는다.
3. 위저드 질문은 모델 `configuration.parameters` 중 **고유값이 2개 이상**인 키만 묻는다. 값이 하나면 잠금(자동 선택)이다.
4. 기준 모델은 센서 **Guralp CMG-3T**, 기록계 **Quanterra Q330HR**.
5. `combine`은 단일 instconfig 또는 `sensor:datalogger` 캐스케이드만 허용한다. `full_NRL_v2_zip`과 쉼표 목록은 거절한다.
6. catalog·prefix-lookup 응답은 Redis에 TTL 캐시한다.

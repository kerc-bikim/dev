# PDCC worker

공식 검증(M3-07)과 dataless SEED 내보내기(M3-04)는 API가 Redis 큐에 넣고, 워커가 스냅샷 XML을 처리합니다.
편집기 요청 스레드에서 대량 변환을 붙잡지 않습니다.

호스트에서:

```bash
cd pdcc_web/apps/api
export DATABASE_URL=postgresql+psycopg://pdcc:pdcc@127.0.0.1:5432/pdcc
export REDIS_URL=redis://127.0.0.1:6379/0
.venv/bin/python -m app.jobs.runner
```

또는 `pdcc_web/apps/worker` 에서 `PYTHONPATH=../api` 로 `python worker.py`.
compose 기본 기동(web, api, postgres, redis)에는 넣지 않습니다.

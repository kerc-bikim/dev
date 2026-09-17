# PDCC worker

RESP·dataless SEED 내보내기는 API가 Redis 큐에 넣고, 워커가 실제로 변환합니다.
API 프로세스에서 큰 변환을 붙잡지 않습니다.

호스트에서:

```bash
cd pdcc_web/apps/api
export DATABASE_URL=postgresql+psycopg://pdcc:pdcc@127.0.0.1:5433/pdcc
export REDIS_URL=redis://127.0.0.1:6379/0
.venv/bin/python -m app.jobs.runner
```

또는 `pdcc_web/apps/worker` 에서 `PYTHONPATH=../api` 로 `python worker.py`.
compose 기본 기동(web, api, postgres, redis)에는 넣지 않습니다. 운영 compose는 M4입니다.

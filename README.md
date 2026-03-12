1. 安装依赖
```bash
pip install uv

uv sync
```

2. 安装redis-server
```bash
sudo apt-get update

sudo apt-get install redis-server
```

3. 启动服务
```bash
#启动redis
redis-server --daemonize yes

#启动worker
uv run celery -A src.app.tasks.worker worker --loglevel=info --concurrency=3

#启动server
uv run src/app/server.py
```
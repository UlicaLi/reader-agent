from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.middleware import auth_middleware, client_info_middleware
from app.config import APP_NAME, APP_DESCRIPTION, ALLOWED_ORIGINS
from app.api.routers import task_router, chat_router, document_router, sse_router

app = FastAPI()
app.title = APP_NAME
app.description = APP_DESCRIPTION

# CORS配置 - 修复环境变量为None的问题
allowed_origins = ALLOWED_ORIGINS
allowed_origins = [origin.strip() for origin in allowed_origins.split(",")]

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

app.middleware("http")(auth_middleware)
app.middleware("http")(client_info_middleware)

app.include_router(task_router)
app.include_router(chat_router)
app.include_router(document_router)
app.include_router(sse_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

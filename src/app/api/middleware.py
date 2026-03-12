from fastapi import Request, HTTPException
from typing import Optional, Dict
import logging
import requests
from urllib.parse import quote
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 不需要认证的路径列表
SKIP_AUTH_PATHS = {
    "/docs",           # Swagger UI 文档
    "/redoc",          # ReDoc 文档  
    "/openapi.json",   # OpenAPI 规范
    "/health",         # 健康检查端点（如果有的话）
    "/metrics",        # 监控指标端点（如果有的话）
    "/favicon.ico",    # 网站图标
}

def should_skip_auth(path: str) -> bool:
    """
    判断是否应该跳过认证检查
    
    Args:
        path (str): 请求路径
        
    Returns:
        bool: 如果应该跳过认证返回True，否则返回False
    """
    # 检查精确匹配
    if path in SKIP_AUTH_PATHS:
        return True
    
    # 检查路径前缀匹配（用于处理带查询参数的情况）
    for skip_path in SKIP_AUTH_PATHS:
        if path.startswith(skip_path):
            return True
    
    return False

def get_current_user(access_token: str) -> Dict:
    """
    通过外部API获取当前用户信息

    Args:
        access_token (str): 访问令牌
        
    Returns:
        Dict: 包含用户信息的字典
        
    Raises:
        HTTPException: 当token无效或API调用失败时抛出401错误
    """
    if not access_token:
        raise HTTPException(status_code=401, detail="No access token provided")

    try:
        # 构建API URL，对access_token进行URL编码
        encoded_token = quote(access_token)
        api_url = f"https://api.noread.pro/api/v1/auth/user?access_token={encoded_token}"
        
        # 调用外部API
        response = requests.get(api_url)
        response.raise_for_status()  # 如果响应状态码不是200，将抛出异常
        
        # 解析响应数据
        user_data = response.json()
        
        # 从响应中提取用户信息
        return {
            "user_uuid": user_data.get("user_id"),  # 根据实际API响应结构调整
            "username": user_data.get("nickname")  # 根据实际API响应结构调整
            # "user_id": "user-uuid-456",
            # "username": "mock_user"
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get user data from API: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def extract_access_token(authorization: str) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


async def auth_middleware(request: Request, call_next):
    # 跳过OPTIONS请求的认证检查（CORS预检请求）
    if request.method == "OPTIONS":
        response = await call_next(request)
        return response

    logger.info(f"request.url: {request.url}")

    # 检查是否需要跳过认证
    if should_skip_auth(request.url.path):
        response = await call_next(request)
        return response
    
    access_token = extract_access_token(request.headers.get("Authorization"))
    
    try:
        current_user = get_current_user(access_token)
    except HTTPException as e:
        return JSONResponse(status_code=401, content={"detail": "No access token provided"})

    

    request.state.current_user = current_user
    response = await call_next(request)
    return response


async def client_info_middleware(request: Request, call_next):
    request.state.device = request.headers.get("X-Device")
    request.state.app_version = request.headers.get("X-App-Version")
    request.state.client_location = request.headers.get("X-Client-Location")
    request.state.client_time = request.headers.get("X-Client-Time")
    response = await call_next(request)
    return response
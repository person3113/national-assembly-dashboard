from fastapi import APIRouter

from app.api.endpoints import members

api_router = APIRouter()
api_router.include_router(members.router, prefix="/members", tags=["members"])
# 다른 엔드포인트도 여기에 추가 가능
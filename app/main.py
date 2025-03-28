"""
국회정보 대시보드 애플리케이션 메인 모듈

이 모듈은 FastAPI 애플리케이션의 진입점으로, 
서버 설정, 미들웨어 구성, 라우터 등록 및 시작 이벤트 처리를 담당합니다.
"""
import logging
import asyncio
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import pass_context

from app.api import api_router
from app.core.config import settings
from app.db.session import engine, get_db
from app.models import member, bill
from app.routes import dashboard_routes, member_routes, bill_routes
from app.services import bill_service, member_service
from app.utils.helpers import clean_duplicate_members, pprint_filter

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 데이터베이스 테이블 생성 - 테이블이 없을 때만 생성
member.Base.metadata.create_all(bind=engine)
bill.Bill.metadata.create_all(bind=engine)

# 서버 시작 시 동기화 상태 추적을 위한 변수
bills_sync_in_progress = False
bills_sync_completed = False

# FastAPI 애플리케이션 생성
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션 환경에서는 보안을 위해 특정 도메인으로 제한해야 함
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 설정
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 템플릿 설정
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["pprint"] = pprint_filter

# 템플릿 객체를 라우트 핸들러에 전달
dashboard_routes.init_templates(templates)
member_routes.init_templates(templates)
bill_routes.init_templates(templates)

# API 라우터 등록
app.include_router(api_router, prefix=settings.API_V1_STR)

# 웹 페이지 라우터 등록
app.include_router(dashboard_routes.router)
app.include_router(member_routes.router)
app.include_router(bill_routes.router)

# 애플리케이션 시작 시 중복 데이터 정리
@app.on_event("startup")
def startup_clean():
    """애플리케이션 시작 시 중복 데이터 정리"""
    db = next(get_db())
    try:
        clean_duplicate_members(db)
    finally:
        db.close()

# 애플리케이션 시작 시 초기 데이터 삽입
@app.on_event("startup")
def startup_event():
    """
    애플리케이션 시작 시 국회의원 데이터를 확인하고 필요한 경우에만 API에서 불러옴
    """
    db = next(get_db())
    try:
        # 기존 데이터 확인
        existing_count = db.query(member.Member).count()
        
        # 이미 적절한 수의 데이터가 있으면 API 호출 건너뛰기
        # 실제 국회의원 수에 맞게 숫자 조정 (여기서는 300명으로 가정)
        if 280 <= existing_count <= 320:  # 약간의 여유를 두고 확인
            logger.info(f"이미 {existing_count}명의 국회의원 데이터가 DB에 존재합니다. API 호출을 건너뜁니다.")
            return
            
        # 데이터 동기화가 필요한 경우, 기존 데이터를 모두 삭제하고 새로 추가
        if existing_count > 0:
            logger.info(f"기존 {existing_count}명의 국회의원 데이터를 삭제하고 새로 불러옵니다.")
            db.query(member.Member).delete()
            db.commit()
            
        # API 키 확인
        api_key = settings.ASSEMBLY_API_KEY
        if not api_key or api_key == "":
            logger.warning("API 키가 설정되지 않았습니다.")
        
        # 국회의원 정보 동기화
        member_count = member_service.sync_members_from_api(db, assembly_term=22)
        logger.info(f"API에서 {member_count}명의 국회의원 데이터를 성공적으로 불러왔습니다.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"초기화 중 오류 발생: {e}")
    finally:
        db.close()

@app.on_event("startup")
async def sync_bills_on_startup():
    """애플리케이션 시작 시 의안 데이터 동기화"""
    global bills_sync_in_progress, bills_sync_completed
    
    # 이미 동기화가 진행 중이거나 완료된 경우 스킵
    if bills_sync_in_progress or bills_sync_completed:
        return
        
    # 백그라운드 작업으로 시작 (서버 시작 블로킹 방지)
    asyncio.create_task(background_sync_bills())

async def background_sync_bills():
    """백그라운드에서 의안 데이터 동기화 수행"""
    global bills_sync_in_progress, bills_sync_completed
    
    try:
        bills_sync_in_progress = True
        logger.info("서버 시작: 의안 데이터 백그라운드 동기화 시작...")
        
        db = next(get_db())
        
        try:
            # 기존 데이터 체크
            bills_count = db.query(bill.Bill).count()
            
            if bills_count < 100:
                # 데이터가 적은 경우 - 전체 동기화
                logger.info(f"의안 데이터 부족 (현재 {bills_count}개). 전체 동기화를 시작합니다.")
                await bill_service.sync_bills_data(db, max_pages=20, incremental=False, fetch_content=True)
            else:
                # 데이터가 이미 있는 경우 - 증분 동기화만 수행
                logger.info(f"의안 데이터가 있습니다 (현재 {bills_count}개). 증분 동기화를 시작합니다.")
                await bill_service.sync_bills_data(db, max_pages=5, incremental=True, fetch_content=True)
                
            logger.info("서버 시작 시 의안 데이터 동기화 완료")
            
        except Exception as e:
            logger.error(f"의안 데이터 동기화 중 오류: {e}")
        finally:
            db.close()
            
        bills_sync_completed = True
    finally:
        bills_sync_in_progress = False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
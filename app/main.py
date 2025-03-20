from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse  # 추가된 부분
from sqlalchemy.orm import Session  # Add this import
from typing import Optional  # Add this import

from app.api import api_router
from app.core.config import settings
from app.db.session import engine, get_db
from app.models import member  # 여기에 모든 모델 모듈 추가
from app.models.member import Member as MemberModel

# 데이터베이스 테이블 생성
member.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션 환경에서는 보안을 위해 특정 도메인으로 제한하세요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 설정
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 템플릿 설정
templates = Jinja2Templates(directory="app/templates")

# API 라우터 등록
app.include_router(api_router, prefix=settings.API_V1_STR)

# 활동 점수 계산 함수
def calculate_activity_score(member: MemberModel) -> float:
    """
    국회의원의 활동 점수를 계산하는 함수
    
    가중치:
    - 발의안 수: 40%
    - 출석률: 30%
    - 발언 횟수: 20%
    - 법안통과율: 10%
    """
    # 각 항목별 정규화를 위한 최대값 (DB에서 조회하는 것이 좋으나 예시로 고정값 사용)
    max_bills = 50
    max_speech_count = 200
    
    # 각 항목별 점수 계산 (0-100 범위)
    bills_score = min(100, (member.num_bills / max_bills) * 100)
    attendance_score = member.attendance_rate  # 이미 0-100 범위
    speech_score = min(100, (member.speech_count / max_speech_count) * 100)
    pass_rate_score = member.bill_pass_rate if member.bill_pass_rate else 0
    
    # 가중치 적용하여 최종 점수 계산
    activity_score = (
        bills_score * 0.4 +
        attendance_score * 0.3 +
        speech_score * 0.2 +
        pass_rate_score * 0.1
    )
    
    return round(activity_score, 1)

# 템플릿 라우트 추가
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/members", response_class=HTMLResponse)
async def members_page(
    request: Request,
    db: Session = Depends(get_db),
    name: Optional[str] = None,
    party: Optional[str] = None,
    district: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    # 국회의원 데이터 조회 로직 (API와 유사)
    query = db.query(MemberModel)
    if name:
        query = query.filter(MemberModel.name.contains(name))
    if party:
        query = query.filter(MemberModel.party == party)
    if district:
        query = query.filter(MemberModel.district.contains(district))
    
    # 페이지네이션
    offset = (page - 1) * limit
    total = query.count()
    members = query.offset(offset).limit(limit).all()
    
    return templates.TemplateResponse(
        "members.html", 
        {
            "request": request,
            "members": members,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "name": name or "",
            "party": party or "",
            "district": district or ""
        }
    )

@app.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail_page(
    request: Request,
    member_id: int,
    db: Session = Depends(get_db)
):
    # 특정 국회의원 조회
    member = db.query(MemberModel).filter(MemberModel.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="국회의원을 찾을 수 없습니다")
    
    return templates.TemplateResponse(
        "member_detail.html", 
        {"request": request, "member": member}
    )

@app.get("/rankings", response_class=HTMLResponse)
async def rankings_page(
    request: Request,
    db: Session = Depends(get_db),
    category: str = "activity",  # 'activity', 'bills', 'speeches', 'attendance'
    party: Optional[str] = None,
    limit: int = 50
):
    # 정렬 기준 설정
    if category == "bills":
        order_by = MemberModel.num_bills.desc()
    elif category == "speeches":
        order_by = MemberModel.speech_count.desc()
    elif category == "attendance":
        order_by = MemberModel.attendance_rate.desc()
    else:  # 기본값: activity
        order_by = MemberModel.activity_score.desc()
    
    # 국회의원 랭킹 조회
    query = db.query(MemberModel)
    if party:
        query = query.filter(MemberModel.party == party)
    
    members = query.order_by(order_by).limit(limit).all()
    
    return templates.TemplateResponse(
        "rankings.html", 
        {
            "request": request,
            "members": members,
            "category": category,
            "party": party
        }
    )

# 활동 점수 업데이트 및 랭킹 생성 작업 스케줄러
@app.on_event("startup")
async def update_activity_scores():
    """
    애플리케이션 시작 시 모든 국회의원의 활동 점수를 계산하여 업데이트
    이후 스케줄러를 통해 주기적으로 실행
    """
    db = next(get_db())
    try:
        members = db.query(MemberModel).all()
        for member in members:
            member.activity_score = calculate_activity_score(member)
        db.commit()
        
        # 추가 작업: 랭킹 정보 캐싱 등
    except Exception as e:
        db.rollback()
        logger.error(f"활동 점수 업데이트 중 오류 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

# 라우트 추가: 필요시 확장 (발의안, 검색 등)
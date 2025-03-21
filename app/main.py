import logging  # Add this import

# Logger 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Depends, HTTPException  # HTTPException 추가
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.api import api_router
from app.core.config import settings
from app.db.session import engine, get_db
from app.models import member  # 여기에 모든 모델 모듈 추가
from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel  # Add this import

# 데이터베이스 테이블 생성
member.Base.metadata.drop_all(bind=engine)  # 기존 테이블 삭제
member.Base.metadata.create_all(bind=engine)  # 새로운 테이블 생성
BillModel.metadata.create_all(bind=engine)  # Add this line

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

# 초기 데이터 삽입 함수
def insert_initial_data(db: Session):
    # 국회의원 데이터 추가
    member1 = MemberModel(
        name="김의원1",
        hanja_name="金議員1",
        eng_name="Kim Euiwon1",
        birth_date=date(1970, 1, 1),
        position="국회의원",
        party="국민의힘",
        district="서울 강남구",
        num_bills=10,
        attendance_rate=95.0,
        speech_count=50,
        activity_score=90.0,
        bill_pass_rate=80.0,  
        is_active=True,
        last_updated=date.today()
    )
    db.add(member1)
    
    # 발의안 데이터 추가
    bill1 = BillModel(
        title="국민건강보험법 일부개정법률안",
        proposer="김의원1",
        status="계류",
        committee="보건복지위원회",
        proposal_date=date(2024, 3, 15),
        content="국민건강보험법 일부를 개정하여 국민의 건강을 증진시키고자 함.",
        proposer_id=1
    )
    db.add(bill1)
    
    db.commit()

# 애플리케이션 시작 시 초기 데이터 삽입
@app.on_event("startup")
async def startup_event():
    db = next(get_db())
    try:
        insert_initial_data(db)
    finally:
        db.close()

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

# 발의안 목록 페이지 라우트 추가
@app.get("/bills", response_class=HTMLResponse)
async def bills_page(
    request: Request,
    db: Session = Depends(get_db),
    title: Optional[str] = None,
    proposer: Optional[str] = None,
    status: Optional[str] = None,
    committee: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    # 발의안 데이터 조회 로직 (필터링 및 페이지네이션 적용)
    query = db.query(BillModel)
    if title:
        query = query.filter(BillModel.title.contains(title))
    if proposer:
        query = query.filter(BillModel.proposer.contains(proposer))
    if status:
        query = query.filter(BillModel.status == status)
    if committee:
        query = query.filter(BillModel.committee == committee)
    
    # 페이지네이션
    offset = (page - 1) * limit
    total = query.count()
    bills = query.offset(offset).limit(limit).all()
    
    return templates.TemplateResponse(
        "bills.html", 
        {
            "request": request,
            "bills": bills,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "title": title or "",
            "proposer": proposer or "",
            "status": status or "",
            "committee": committee or ""
        }
    )

# 발의안 상세 페이지 라우트 추가
@app.get("/bills/{bill_id}", response_class=HTMLResponse)
async def bill_detail_page(
    request: Request,
    bill_id: int,
    db: Session = Depends(get_db)
):
    # 특정 발의안 조회
    bill = db.query(BillModel).filter(BillModel.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="발의안을 찾을 수 없습니다")
    
    return templates.TemplateResponse(
        "bill_detail.html", 
        {"request": request, "bill": bill}
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
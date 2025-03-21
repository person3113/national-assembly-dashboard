import logging  
import pprint
import requests 
import asyncio
import time  # asyncio 대체용

from fastapi import FastAPI, Request, Depends, HTTPException  # HTTPException 추가
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, datetime

from app.api import api_router
from app.core.config import settings
from app.db.session import engine, get_db
from app.models import member  # 여기에 모든 모델 모듈 추가
from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel  
from app.services.assembly_api import assembly_api

# 템플릿에서 사용할 필터 추가
from jinja2 import pass_context

@pass_context
def pprint_filter(context, value):
    return pprint.pformat(value)

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
templates.env.filters["pprint"] = pprint_filter

# Logger 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

async def sync_member_bills(db: Session):
    """국회의원별 발의안 정보를 API에서 가져와 DB에 저장"""
    try:
        logger.info("국회의원 발의안 정보 동기화 시작...")
        
        # 현재 데이터베이스의 모든 국회의원 조회
        members = db.query(MemberModel).all()
        
        # 총 처리된 발의안 수 카운터
        total_bills = 0
        
        for member in members:
            logger.info(f"{member.name} 의원의 발의안 정보 조회 중...")
            
            # 기존 발의안 삭제 (재동기화)
            db.query(BillModel).filter(BillModel.proposer_id == member.id).delete()
            
            # API에서 해당 의원이 발의한 법안 조회
            try:
                # API 호출 방식 수정 - PPSR_NM 파라미터 사용 (직접 테스트 필요)
                # 현재는 의원명이 아닌 의안번호로 API 호출하고 있음
                bills_data = []
                
                # 모든 국회의원에게 발의안이 없을 수 있으므로 에러 발생 시에도 진행
                try:
                    # 22대 국회 시작일부터 현재까지 기간 설정
                    start_date = "20240530"  # 22대 국회 시작일
                    end_date = datetime.now().strftime("%Y%m%d")
                    
                    # API 호출 - 의원 이름으로 검색 (API 문서 확인 필요)
                    bills_data = assembly_api.get_bills(
                        bill_name="",  # 빈 값으로 설정
                        proposer=member.name,  # 제안자 이름
                        start_date=start_date,
                        end_date=end_date
                    )
                except Exception as api_error:
                    logger.warning(f"{member.name} 의원의 발의안 조회 중 API 오류: {api_error}")
                    bills_data = []  # 오류 발생 시 빈 리스트로 설정
                
                # 발의안 수 업데이트
                member.num_bills = len(bills_data)
                
                # 각 발의안 데이터 처리
                for bill_data in bills_data[:10]:  # 최근 10개만 저장
                    try:
                        # 날짜 포맷 변환
                        proposal_date = None
                        if bill_data.get("PPSL_DT"):
                            try:
                                proposal_date = datetime.strptime(
                                    bill_data.get("PPSL_DT"), "%Y-%m-%d"
                                ).date()
                            except ValueError:
                                proposal_date = datetime.now().date()
                        
                        # 발의안 저장
                        new_bill = BillModel(
                            title=bill_data.get("BILL_NM", "제목 없음"),
                            proposer=member.name,
                            status=bill_data.get("PROC_RESULT", "계류"),
                            committee=bill_data.get("COMMITTEE", "정보 없음"),
                            proposal_date=proposal_date or datetime.now().date(),
                            content=bill_data.get("DETAIL_CONTENT", "내용 없음"),
                            co_proposers=bill_data.get("PUBL_PROPOSER", ""),
                            proposer_id=member.id
                        )
                        db.add(new_bill)
                        total_bills += 1
                    except Exception as e:
                        logger.error(f"발의안 데이터 처리 중 오류: {e}")
                
            except Exception as e:
                logger.error(f"{member.name} 의원의 발의안 조회 중 오류: {e}")
                # 오류 발생 시에도 계속 진행
                continue
            
            # API 호출 간 지연 (asyncio 대신 time.sleep 사용)
            # await asyncio.sleep(1) 대신 다음 코드 사용
            time.sleep(0.5)
        
        # 모든 국회의원 처리 후 커밋
        db.commit()
        logger.info(f"국회의원 발의안 정보 동기화 완료. 총 {total_bills}개 발의안 처리됨.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"발의안 정보 동기화 중 오류 발생: {e}")

# 애플리케이션 시작 시 초기 데이터 삽입
@app.on_event("startup")
def startup_event():
    """애플리케이션 시작 시 국회의원 데이터를 API에서 불러와 초기 데이터 준비"""
    db = next(get_db())
    try:
        # API 키 확인
        api_key = settings.ASSEMBLY_API_KEY
        if not api_key or api_key == "":
            logger.warning("API 키가 설정되지 않았습니다. 샘플 데이터를 사용합니다.")
            # API 키가 없을 경우 샘플 데이터 사용
            members_count = db.query(MemberModel).count()
            if members_count == 0:
                insert_initial_data(db)
                logger.info("샘플 데이터 삽입 완료")
            return
        
        # API에서 국회의원 목록 조회
        logger.info("API에서 국회의원 데이터를 불러오는 중...")
        members_data = assembly_api.get_members(assembly_term=22)  # 22대 국회의원 기본값
        
        if not members_data:
            logger.warning("API에서 데이터를 가져오지 못했습니다. 샘플 데이터를 사용합니다.")
            members_count = db.query(MemberModel).count()
            if members_count == 0:
                insert_initial_data(db)
            return
        
        # 기존 데이터 확인 - 이미 데이터가 있으면 삭제 후 새로 추가
        existing_count = db.query(MemberModel).count()
        if existing_count > 0:
            logger.info(f"기존 {existing_count}개의 국회의원 데이터를 삭제합니다.")
            db.query(MemberModel).delete()
        
        # API 데이터 추가
        member_count = 0
        for member_data in members_data:
            try:
                # 생년월일 변환
                birth_date = None
                if member_data.get("BTH_DATE"):
                    try:
                        birth_date_str = member_data.get("BTH_DATE")
                        
                        # 날짜 형식 확인 및 변환
                        if "-" in birth_date_str:  # YYYY-MM-DD 형식
                            birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
                        elif len(birth_date_str) == 8:  # YYYYMMDD 형식
                            birth_date = datetime.strptime(birth_date_str, "%Y%m%d").date()
                        else:
                            # 다른 형식이 있을 경우 로그만 남기고 계속 진행
                            logger.warning(f"지원하지 않는 생년월일 형식: {birth_date_str}")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"생년월일 변환 오류 ({birth_date_str}): {e}")
                
                # 국회의원 데이터 생성
                new_member = MemberModel(
                    name=member_data.get("HG_NM", ""),  # 이름
                    hanja_name=member_data.get("HJ_NM", ""),  # 한자명
                    eng_name=member_data.get("ENG_NM", ""),  # 영문명
                    birth_date=birth_date,  # 생년월일
                    birth_gbn=member_data.get("BTH_GBN_NM", ""),  # 음/양력
                    party=member_data.get("POLY_NM", ""),  # 정당명
                    district=member_data.get("ORIG_NM", ""),  # 선거구
                    position=member_data.get("JOB_RES_NM", ""),  # 직책명
                    
                    # 추가 필드
                    committee=member_data.get("CMIT_NM", ""),  # 대표 위원회
                    committees=member_data.get("CMITS", ""),  # 소속 위원회 목록
                    reele_gbn=member_data.get("REELE_GBN_NM", ""),  # 재선 구분
                    units=member_data.get("UNITS", ""),  # 당선 수
                    
                    # 연락처 정보
                    tel_no=member_data.get("TEL_NO", ""),  # 전화번호
                    email=member_data.get("E_MAIL", ""),  # 이메일
                    homepage=member_data.get("HOMEPAGE", ""),  # 홈페이지
                    
                    # 기본값
                    num_bills=0,
                    attendance_rate=0.0,
                    speech_count=0,
                    activity_score=0.0,
                    is_active=True,
                    last_updated=datetime.now().date()
                )
                db.add(new_member)
                member_count += 1
            except Exception as e:
                logger.error(f"국회의원 데이터 추가 중 오류: {e}")
        
        # 커밋
        db.commit()
        logger.info(f"API에서 {member_count}명의 국회의원 데이터를 성공적으로 불러왔습니다.")
        
        # 활동 점수 계산 및 발의안 동기화
        try:
            # 활동 점수 계산
            members = db.query(MemberModel).all()
            for member in members:
                member.activity_score = calculate_activity_score(member)
            db.commit()
            
            # 발의안 정보 동기화 (비동기 함수를 일반 함수로 호출)
            sync_member_bills(db)
        except Exception as e:
            logger.error(f"활동 점수 계산 및 발의안 동기화 중 오류: {e}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"초기화 중 오류 발생: {e}")
        # 오류 발생 시 기본 데이터 확인
        members_count = db.query(MemberModel).count()
        if members_count == 0:
            try:
                insert_initial_data(db)
                logger.info("오류 발생으로 샘플 데이터 삽입 완료")
            except Exception as e2:
                logger.error(f"샘플 데이터 삽입 중 오류: {e2}")
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
    # 국회의원 데이터 조회 로직
    query = db.query(MemberModel)
    if name:
        query = query.filter(MemberModel.name.contains(name))
    if party:
        query = query.filter(MemberModel.party == party)
    if district:
        query = query.filter(MemberModel.district.contains(district))
    
    # 총 레코드 수와 페이지 수 계산
    total = query.count()
    total_pages = (total + limit - 1) // limit
    
    # 페이지 범위 검증
    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages
    
    # 오프셋 계산 및 데이터 조회
    offset = (page - 1) * limit
    members = query.offset(offset).limit(limit).all()
    
    # 페이지네이션 범위 설정 (현재 페이지 주변 5개 페이지 표시)
    if total_pages <= 5:
        page_range = range(1, total_pages + 1)
    else:
        start_page = max(1, page - 2)
        end_page = min(total_pages, page + 2)
        page_range = range(start_page, end_page + 1)
    
    return templates.TemplateResponse(
        "members.html", 
        {
            "request": request,
            "members": members,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "page_range": page_range,
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
    """국회의원 상세 정보 페이지"""
    # 특정 국회의원 조회
    member = db.query(MemberModel).filter(MemberModel.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="국회의원을 찾을 수 없습니다")
    
    # 추가 데이터 수집
    try:
        # 국회의원 발의안 목록 조회 (최근 5개)
        bills = db.query(BillModel).filter(BillModel.proposer_id == member_id).order_by(BillModel.proposal_date.desc()).limit(5).all()
        
        # 발언 목록 가져오기 (API 호출)
        speech_data = []
        try:
            # API에서 해당 의원의 발언 데이터 조회 - API 엔드포인트 수정됨
            speech_records = assembly_api.get_speech_records(member_name=member.name)
            # 최근 5개만 선택
            speech_data = speech_records[:5] if len(speech_records) > 0 else []
            logger.info(f"{member.name} 의원의 발언 데이터 {len(speech_data)}개 조회 성공")
        except Exception as e:
            logger.error(f"발언 데이터 조회 중 오류: {e}")
            # API 오류 시 빈 리스트로 설정
            speech_data = []
        
        # 발언 데이터 포맷팅
        speeches = []
        for speech in speech_data:
            speeches.append({
                "meeting_type": speech.get("TITLE", "본회의"),  # 회의제목
                "date": speech.get("TAKING_DATE", ""),  # 회의일자
                "content": speech.get("CONTENT", "발언 내용이 제공되지 않습니다.")[:100] + "...",  # 내용 요약 (없으면 기본 메시지)
                "topic": speech.get("TOPIC", "일반 발언"),  # 주제 (없으면 기본값)
                "link": speech.get("LINK_URL", "#")  # 링크 (없으면 #)
            })
            
        # 데이터 부족 시 기본 데이터로 보완
        if len(speeches) == 0:
            # API 응답 없을 경우 더미 데이터 제공
            speeches = [
                {
                    "meeting_type": meeting_type,
                    "date": f"2024-03-{10-i}",
                    "content": "API에서 발언 데이터를 가져올 수 없습니다. 국회정보 API를 확인해주세요.",
                    "topic": topic,
                    "link": "#"
                }
                for i, (meeting_type, topic) in enumerate(zip(
                    ["본회의", "상임위원회", "국정감사", "법안심사소위원회", "예산결산심사소위원회"],
                    ["경제", "환경", "복지", "교육", "안보"]
                ))
            ]
        
        # 의원 활동 지표 계산 
        activity_data = {
            "member": {
                "bills": (member.num_bills / 50) * 100 if member.num_bills else 85,  # 최대값 대비 비율 계산
                "attendance": member.attendance_rate if member.attendance_rate else 95,
                "speeches": (member.speech_count / 200) * 100 if member.speech_count else 90,
                "pass_rate": member.bill_pass_rate if member.bill_pass_rate else 75,
                "committee": 88  # 상임위 활동은 기본값 유지 (데이터 없음)
            },
            "average": {
                "bills": 70,
                "attendance": 80,
                "speeches": 65,
                "pass_rate": 60,
                "committee": 75
            }
        }
        
        return templates.TemplateResponse(
            "member_detail.html", 
            {
                "request": request, 
                "member": member,
                "bills": bills,
                "speeches": speeches,
                "activity_data": activity_data
            }
        )
        
    except Exception as e:
        logger.error(f"국회의원 상세 정보 조회 중 오류: {e}")
        # 오류 발생 시에도 기본 정보는 표시
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
    bill_no: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    """발의안 목록 페이지"""
    try:
        # 의안번호 검색 시에만 API 호출
        if bill_no:
            # API에서 발의안 데이터 가져오기
            bills_data = assembly_api.get_bills(
                bill_name=title,
                proposer=proposer,
                committee=committee,
                bill_no=bill_no,
                page_index=page,
                page_size=limit
            )
            
            # 가져온 데이터를 처리하여 표시
            bills = []
            for bill_data in bills_data:
                bill = {
                    "id": bill_data.get("BILL_ID", ""),
                    "no": bill_data.get("BILL_NO", ""),
                    "title": bill_data.get("BILL_NM", ""),
                    "proposer": bill_data.get("PPSR_NM", ""),
                    "committee": bill_data.get("JRCMIT_NM", ""),
                    "proposal_date": bill_data.get("PPSL_DT", ""),
                    "status": bill_data.get("RGS_CONF_RSLT", "계류") if bill_data.get("RGS_CONF_RSLT") else "계류"
                }
                bills.append(bill)
        else:
            # 의안번호 없이 전체 조회는 불가능하므로 안내 메시지 표시
            bills = []
        
        # 페이지네이션 정보 계산
        has_next = len(bills) == limit
        has_prev = page > 1
        
        # 화면에 표시할 데이터 구성
        context = {
            "request": request,
            "bills": bills,
            "page": page,
            "limit": limit,
            "has_next": has_next,
            "has_prev": has_prev,
            "title": title or "",
            "proposer": proposer or "",
            "status": status or "",
            "committee": committee or "",
            "bill_no": bill_no or "",
            "info_message": "의안번호를 입력하시면 해당 의안정보를 검색할 수 있습니다." if not bill_no else None
        }
        
        return templates.TemplateResponse("bills.html", context)
    
    except Exception as e:
        logger.error(f"발의안 목록 조회 중 오류: {e}")
        
        # 오류 발생 시 빈 목록 반환
        return templates.TemplateResponse(
            "bills.html", 
            {
                "request": request,
                "bills": [],
                "page": page,
                "limit": limit,
                "has_next": False,
                "has_prev": page > 1,
                "title": title or "",
                "proposer": proposer or "",
                "status": status or "",
                "committee": committee or "",
                "bill_no": bill_no or "",
                "error_message": f"발의안 데이터를 가져오는 중 오류가 발생했습니다: {str(e)}"
            }
        )

# 발의안 상세 페이지 라우트 추가
@app.get("/bills/{bill_no}", response_class=HTMLResponse)
async def bill_detail_page(
    request: Request,
    bill_no: str,
    db: Session = Depends(get_db)
):
    """발의안 상세 페이지"""
    try:
        # API에서 발의안 상세 정보 가져오기
        bill_data = assembly_api.get_bill_detail(bill_no=bill_no)
        
        # 발의안을 찾지 못한 경우 404 오류
        if not bill_data:
            raise HTTPException(status_code=404, detail="발의안을 찾을 수 없습니다")
        
        # 3. 발의안 정보 구성
        bill = {
            "id": bill_data.get("BILL_ID", ""),
            "no": bill_data.get("BILL_NO", ""),
            "title": bill_data.get("BILL_NM", ""),
            "proposer": bill_data.get("PPSR_NM", ""),
            "committee": bill_data.get("JRCMIT_NM", ""),
            "proposal_date": bill_data.get("PPSL_DT", ""),
            "status": bill_data.get("RGS_CONF_RSLT", "계류") if bill_data.get("RGS_CONF_RSLT") else "계류",
            "link_url": bill_data.get("LINK_URL", ""),
            
            # 처리 경과 정보
            "committee_refer_date": bill_data.get("JRCMIT_CMMT_DT", ""),  # 소관위 회부일
            "committee_present_date": bill_data.get("JRCMIT_PRSNT_DT", ""),  # 소관위 상정일
            "committee_proc_date": bill_data.get("JRCMIT_PROC_DT", ""),  # 소관위 처리일
            "committee_proc_result": bill_data.get("JRCMIT_PROC_RSLT", ""),  # 소관위 처리결과
            
            "law_committee_refer_date": bill_data.get("LAW_CMMT_DT", ""),  # 법사위 회부일
            "law_committee_present_date": bill_data.get("LAW_PRSNT_DT", ""),  # 법사위 상정일
            "law_committee_proc_date": bill_data.get("LAW_PROC_DT", ""),  # 법사위 처리일
            "law_committee_proc_result": bill_data.get("LAW_PROC_RSLT", ""),  # 법사위 처리결과
            
            "plenary_present_date": bill_data.get("RGS_PRSNT_DT", ""),  # 본회의 상정일
            "plenary_resolve_date": bill_data.get("RGS_RSLN_DT", ""),  # 본회의 의결일
            "plenary_result": bill_data.get("RGS_CONF_RSLT", "")  # 본회의 결과
        }
        
        # 4. 처리 경과 정보 생성
        process_history = []
        
        # 제안일
        if bill["proposal_date"]:
            process_history.append({
                "date": bill["proposal_date"],
                "content": "발의"
            })
        
        # 소관위원회 회부일
        if bill["committee_refer_date"]:
            process_history.append({
                "date": bill["committee_refer_date"],
                "content": f"소관위원회({bill['committee']}) 회부"
            })
        
        # 소관위원회 상정일
        if bill["committee_present_date"]:
            process_history.append({
                "date": bill["committee_present_date"],
                "content": f"소관위원회 상정"
            })
        
        # 소관위원회 처리일
        if bill["committee_proc_date"]:
            process_history.append({
                "date": bill["committee_proc_date"],
                "content": f"소관위원회 의결: {bill['committee_proc_result']}"
            })
        
        # 법사위 회부일
        if bill["law_committee_refer_date"]:
            process_history.append({
                "date": bill["law_committee_refer_date"],
                "content": "법제사법위원회 회부"
            })
        
        # 본회의 의결일
        if bill["plenary_resolve_date"]:
            process_history.append({
                "date": bill["plenary_resolve_date"],
                "content": f"본회의 의결: {bill['plenary_result']}"
            })
        
        # 처리 경과 정보 추가
        bill["process_history"] = sorted(process_history, key=lambda x: x["date"])
        
        return templates.TemplateResponse("bill_detail.html", {"request": request, "bill": bill})
    
    except HTTPException:
        # 리소스를 찾을 수 없는 경우
        raise
    
    except Exception as e:
        logger.error(f"발의안 상세 정보 조회 중 오류: {e}")
        
        # 오류 발생 시 더미 데이터로 화면 보여주기
        dummy_bill = {
            "no": bill_no,
            "title": "발의안 정보를 가져올 수 없습니다",
            "proposer": "정보 없음",
            "committee": "정보 없음",
            "proposal_date": "정보 없음",
            "status": "정보 없음",
            "content": f"발의안 상세 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"
        }
        
        return templates.TemplateResponse("bill_detail.html", {"request": request, "bill": dummy_bill})

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

@app.get("/admin/sync-data", response_class=HTMLResponse)
async def sync_data(request: Request, db: Session = Depends(get_db), assembly_term: int = 22):
    """국회정보 API에서 데이터를 가져와 DB에 동기화하는 관리자 페이지"""
    result = {"success": False, "message": "", "counts": {}, "debug_info": {}}
    
    try:
        # API 키 확인
        api_key = settings.ASSEMBLY_API_KEY
        if not api_key or api_key == "":
            result["message"] = "API 키가 설정되지 않았습니다. .env 파일을 확인하세요."
            return templates.TemplateResponse(
                "admin/sync_data.html", 
                {"request": request, "result": result}
            )
        
        # 디버깅을 위한 정보 수집
        result["debug_info"]["api_key_exists"] = bool(api_key)
        result["debug_info"]["api_base_url"] = settings.ASSEMBLY_API_BASE_URL
        
        # 1. 국회의원 정보 동기화
        members_data = assembly_api.get_members(assembly_term=assembly_term)
        
        # 디버깅: API 응답 확인
        result["debug_info"]["members_data_count"] = len(members_data)
        
        # 데이터가 없으면 오류 메시지 반환
        if not members_data:
            result["message"] = "API에서 국회의원 데이터를 가져오지 못했습니다. 로그를 확인하세요."
            return templates.TemplateResponse(
                "admin/sync_data.html", 
                {"request": request, "result": result}
            )
        
        # 이하 기존 코드와 동일...
        member_count = 0
        
        for member_data in members_data:
            # 이미 존재하는 의원인지 확인
            existing_member = db.query(MemberModel).filter(
                MemberModel.name == member_data.get("HG_NM", "")
            ).first()
            
            if existing_member:
                # 기존 데이터 업데이트
                existing_member.party = member_data.get("POLY_NM", "")
                existing_member.district = member_data.get("ORIG_NM", "")
                existing_member.position = member_data.get("CURR_COMMITTEE", "")
                existing_member.last_updated = datetime.now().date()
            else:
                # 새로운 의원 데이터 생성
                new_member = MemberModel(
                    name=member_data.get("HG_NM", ""),
                    hanja_name=member_data.get("HJ_NM", ""),
                    eng_name=member_data.get("ENG_NM", ""),
                    party=member_data.get("POLY_NM", ""),
                    district=member_data.get("ORIG_NM", ""),
                    position=member_data.get("CURR_COMMITTEE", ""),
                    num_bills=0,
                    attendance_rate=0.0,
                    speech_count=0,
                    activity_score=0.0,
                    is_active=True,
                    last_updated=datetime.now().date()
                )
                db.add(new_member)
                member_count += 1
        
        # 3. 활동 점수 계산
        members = db.query(MemberModel).all()
        for member in members:
            member.activity_score = calculate_activity_score(member)
        
        db.commit()
        result["success"] = True
        result["message"] = "데이터 동기화 완료"
        result["counts"] = {"members": member_count}
        
    except Exception as e:
        db.rollback()
        result["message"] = f"오류 발생: {str(e)}"
        result["debug_info"]["error"] = str(e)
        logger.error(f"API 데이터 동기화 중 오류: {e}")
    
    return templates.TemplateResponse(
        "admin/sync_data.html", 
        {"request": request, "result": result}
    )

@app.get("/admin/test-api", response_class=HTMLResponse)
async def test_api(request: Request):
    """API 연결 테스트 페이지"""
    result = {"success": False, "message": "", "data": None}
    
    try:
        # API 키 확인
        api_key = settings.ASSEMBLY_API_KEY
        if not api_key or api_key == "":
            result["message"] = "API 키가 설정되지 않았습니다. .env 파일을 확인하세요."
            return templates.TemplateResponse(
                "admin/test_api.html", 
                {"request": request, "result": result}
            )
        
        # 간단한 API 호출 테스트
        url = f"{settings.ASSEMBLY_API_BASE_URL}/nwvrqwxyaytdsfvhu"
        params = {
            "KEY": api_key,
            "Type": "json",
            "ASSEMBLY": 22,
            "pIndex": 1,
            "pSize": 1
        }
        
        # 요청 보내기
        response = requests.get(url, params=params)
        
        # 결과 확인
        result["status_code"] = response.status_code
        if response.status_code == 200:
            result["data"] = response.json()
            result["success"] = True
            result["message"] = "API 호출 성공"
        else:
            result["message"] = f"API 호출 실패: {response.status_code}, {response.text}"
        
    except Exception as e:
        result["message"] = f"오류 발생: {str(e)}"
        logging.error(f"API 테스트 중 오류: {e}")
    
    return templates.TemplateResponse(
        "admin/test_api.html", 
        {"request": request, "result": result}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

# 라우트 추가: 필요시 확장 (발의안, 검색 등)
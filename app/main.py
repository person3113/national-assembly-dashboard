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

# APScheduler 패키지 설치 필요: pip install apscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 템플릿에서 사용할 필터 추가
from jinja2 import pass_context

@pass_context
def pprint_filter(context, value):
    return pprint.pformat(value)

# 전역 변수로 동기화 상태 추적
bills_sync_in_progress = False
bills_sync_completed = False

# 스케줄러 생성
scheduler = AsyncIOScheduler()


# 데이터베이스 테이블 생성 - 테이블이 없을 때만 생성
# member.Base.metadata.drop_all(bind=engine)  # 이 줄을 제거하거나 주석 처리
member.Base.metadata.create_all(bind=engine)  # 테이블이 없으면 생성
BillModel.metadata.create_all(bind=engine)  # 테이블이 없으면 생성

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# 스케줄러 작업: 매일 새벽 2시에 의안 데이터 동기화
@app.on_event("startup")
def setup_scheduler():
    """애플리케이션 시작 시 스케줄러 설정"""
    # 매일 새벽 2시에 의안 데이터 업데이트
    scheduler.add_job(
        scheduled_sync_bills,
        CronTrigger(hour=2, minute=0),
        id="daily_bills_sync"
    )
    
    # 매주 일요일 새벽 3시에 의안 데이터 전체 업데이트 (기존 데이터도 업데이트)
    scheduler.add_job(
        scheduled_full_sync_bills,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly_full_bills_sync"
    )
    
    # 스케줄러 시작
    scheduler.start()

async def scheduled_sync_bills():
    """스케줄러에서 실행되는 의안 데이터 동기화 함수"""
    logger.info("스케줄러: 일일 의안 데이터 동기화 시작")
    
    db = next(get_db())
    try:
        # 증분 업데이트 방식으로 최신 의안만 추가
        await sync_bills_data(db, max_pages=5, update_existing=True, incremental=True)
    except Exception as e:
        logger.error(f"스케줄러 의안 동기화 중 오류: {e}")
    finally:
        db.close()

async def scheduled_full_sync_bills():
    """스케줄러에서 실행되는 의안 데이터 전체 동기화 함수"""
    logger.info("스케줄러: 주간 의안 데이터 전체 동기화 시작")
    
    db = next(get_db())
    try:
        # 1. 최근 데이터 업데이트 (기존 데이터도 업데이트)
        await sync_bills_data(db, max_pages=10, update_existing=True, incremental=True)
        
        # 2. 누락된 데이터 검사 및 보완 (선택적)
        # 이 부분은 필요할 경우 구현
        
    except Exception as e:
        logger.error(f"스케줄러 전체 의안 동기화 중 오류: {e}")
    finally:
        db.close()

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

async def sync_bills_data(db: Session, max_pages: int = 10, update_existing: bool = False, incremental: bool = True, fetch_content: bool = True):
    """
    의안 데이터를 API에서 가져와 DB에 동기화하는 비동기 함수
    
    Args:
        db: 데이터베이스 세션
        max_pages: 처리할 최대 페이지 수
        update_existing: 기존 의안 정보도 업데이트할지 여부
        incremental: 증분 업데이트 여부 (최근 의안만 가져올지)
        fetch_content: 의안 상세 내용을 가져올지 여부
    """
    try:
        logger.info(f"의안 정보 동기화 시작... (최대 {max_pages} 페이지)")
        
        # 증분 업데이트 시 가장 최근에 추가된 의안의 발의일 확인
        latest_date = None
        if incremental:
            latest_bill = db.query(BillModel).order_by(BillModel.proposal_date.desc()).first()
            if latest_bill and latest_bill.proposal_date:
                latest_date = latest_bill.proposal_date
                logger.info(f"증분 업데이트: {latest_date} 이후 의안만 가져옵니다.")
        
        current_page = 1
        page_size = 100
        total_bills = 0
        updated_bills = 0
        skipped_bills = 0
        
        while current_page <= max_pages:
            logger.info(f"의안 목록 페이지 {current_page} 조회 중...")
            
            # API에서 의안 목록 가져오기
            bills_data = assembly_api.get_bill_ids_by_age(
                assembly_term=22,
                page_index=current_page,
                page_size=page_size
            )
            
            if not bills_data:
                logger.info(f"더 이상 의안 데이터가 없거나 페이지 {current_page}에서 데이터를 가져오지 못했습니다.")
                break
                
            # 각 의안 정보 DB에 저장
            page_new_bills = 0
            for i, bill_data in enumerate(bills_data):
                try:
                    # 의안번호와 의안ID 추출
                    bill_id = bill_data.get("BILL_ID", "")
                    bill_no = bill_data.get("BILL_NO", "")
                    
                    if not bill_id or not bill_no:
                        logger.warning(f"의안ID 또는 의안번호가 없는 데이터 건너뜀")
                        continue
                    
                    # 날짜 변환
                    proc_date = None
                    if bill_data.get("PROC_DT"):
                        try:
                            proc_date = datetime.strptime(bill_data.get("PROC_DT"), "%Y-%m-%d").date()
                        except ValueError:
                            proc_date = None
                    
                    # 증분 업데이트 시 최신 날짜보다 오래된 의안은 건너뜀
                    if incremental and latest_date and proc_date and proc_date <= latest_date:
                        skipped_bills += 1
                        continue
                        
                    # 이미 저장된 의안인지 확인
                    existing_bill = db.query(BillModel).filter(BillModel.bill_id == bill_id).first()
                    
                    # 기존 데이터가 있는 경우 처리
                    if existing_bill:
                        # 업데이트 옵션이 켜져 있으면 기존 데이터 업데이트
                        if update_existing:
                            existing_bill.status = bill_data.get("PROC_RESULT_CD", existing_bill.status)
                            existing_bill.vote_result = bill_data.get("PROC_RESULT_CD")
                            existing_bill.last_updated = datetime.now()
                            
                            # 표결 정보 업데이트
                            if bill_data.get("PROC_DT"):
                                try:
                                    existing_bill.vote_date = proc_date
                                except ValueError:
                                    pass
                                    
                            updated_bills += 1
                        else:
                            skipped_bills += 1
                        continue
                    
                    # 제안자 정보 조회 및 설정 (bill_data 자체도 함께 전달)
                    proposers_info = assembly_api.get_bill_proposers(bill_id, bill_data)
                    rep_proposer = proposers_info.get("rep_proposer")
                    co_proposers = proposers_info.get("co_proposers", [])
                    
                    # 의안명에서 발의자 정보 추출 시도 (이미 get_bill_proposers에서 시도했지만 실패한 경우 여기서 재시도)
                    if not rep_proposer:
                        bill_name = bill_data.get("BILL_NAME", "")
                        try:
                            if ")" in bill_name and "(" in bill_name:
                                parts = bill_name.split("(")
                                if len(parts) > 1:
                                    proposer_part = parts[-1].split(")")[0]
                                    if "의원" in proposer_part:
                                        rep_proposer = proposer_part.split("의원")[0] + "의원"
                                    elif "위원장" in proposer_part:
                                        rep_proposer = proposer_part
                                    elif "정부" in proposer_part:
                                        rep_proposer = "정부"
                        except:
                            pass
                    
                    # 새 의안 데이터 생성
                    new_bill = BillModel(
                        bill_id=bill_id,
                        bill_no=bill_no,
                        title=bill_data.get("BILL_NAME", ""),
                        committee=bill_data.get("CURR_COMMITTEE", ""),
                        status=bill_data.get("PROC_RESULT_CD", "계류"),
                        proposal_date=proc_date,
                        content="",  # 상세 내용은 별도 API 호출 필요
                        bill_kind=bill_data.get("BILL_KIND_CD", ""),
                        vote_result=bill_data.get("PROC_RESULT_CD"),
                        vote_date=proc_date,
                        rep_proposer=rep_proposer,
                        proposer=rep_proposer or bill_data.get("BILL_KIND_CD", "").endswith("(정부)") and "정부" or "",
                        co_proposers=", ".join(co_proposers) if co_proposers else None
                    )
                    
                    # 대표 발의자가 있으면 의원 테이블에서 조회하여 연결
                    if rep_proposer and "위원장" not in rep_proposer and rep_proposer != "정부":
                        proposer_member = db.query(MemberModel).filter(
                            MemberModel.name == rep_proposer
                        ).first()
                        
                        if proposer_member:
                            new_bill.proposer_id = proposer_member.id
                            
                            # 의원의 발의안 수 증가
                            proposer_member.num_bills += 1
                    
                    db.add(new_bill)
                    total_bills += 1
                    page_new_bills += 1
                    
                    # 20건마다 커밋
                    if total_bills > 0 and total_bills % 20 == 0:
                        db.commit()
                        logger.info(f"현재까지 {total_bills}개 신규 의안, {updated_bills}개 업데이트, {skipped_bills}개 건너뜀")
                    
                    # API 과부하 방지를 위한 대기 - 제안자 정보 API 실패 횟수가 임계값에 도달하면 대기 시간 단축
                    if assembly_api.proposer_api_fail_count >= assembly_api.max_proposer_api_fails:
                        # 연속 실패가 많으면 대기 시간 단축
                        if i > 0 and i % 10 == 0:
                            await asyncio.sleep(0.2)
                    else:
                        # 일반적인 대기 시간
                        if i > 0 and i % 5 == 0:
                            await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"의안 ID {bill_id} 처리 중 오류: {e}")
                    continue
            
            # 커밋
            db.commit()
            logger.info(f"페이지 {current_page} 처리 완료. 페이지 내 신규 의안: {page_new_bills}개, 전체: {total_bills}개 신규, {updated_bills}개 업데이트, {skipped_bills}개 건너뜀")
            
            # 증분 업데이트 시 한 페이지에서 새 의안이 없으면 더 이상 진행할 필요 없음
            if incremental and page_new_bills == 0:
                logger.info("증분 업데이트: 이 페이지에서 새 의안이 없으므로 동기화를 종료합니다.")
                break
            
            # 다음 페이지로
            current_page += 1
            
            # API 과부하 방지
            await asyncio.sleep(1)
        
        logger.info(f"의안 정보 동기화 완료. 총 {total_bills}개 신규 의안, {updated_bills}개 업데이트, {skipped_bills}개 건너뜀")
        return total_bills
        
    except Exception as e:
        db.rollback()
        logger.error(f"의안 정보 동기화 중 오류 발생: {e}")
        return 0

# 이 함수를 startup_event 앞에 추가합니다
def clean_duplicate_data():
    """중복된 국회의원 데이터를 제거합니다"""
    db = next(get_db())
    try:
        # 현재 데이터 수 확인
        total_count = db.query(MemberModel).count()
        logger.info(f"정리 전 국회의원 데이터: {total_count}명")
        
        # 중복 데이터를 확인하기 위한 집합
        unique_names = set()
        duplicate_ids = []
        
        # 모든 국회의원 데이터 조회
        members = db.query(MemberModel).all()
        for member in members:
            if member.name in unique_names:
                # 이미 처리한 이름이면 중복으로 판단
                duplicate_ids.append(member.id)
            else:
                unique_names.add(member.name)
        
        # 중복 데이터 삭제
        if duplicate_ids:
            for dup_id in duplicate_ids:
                db.query(MemberModel).filter(MemberModel.id == dup_id).delete()
            db.commit()
            
        # 정리 후 데이터 수 확인
        final_count = db.query(MemberModel).count()
        logger.info(f"정리 후 국회의원 데이터: {final_count}명")
        logger.info(f"총 {total_count - final_count}개의 중복 데이터가 제거되었습니다.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"중복 데이터 정리 중 오류 발생: {e}")
    finally:
        db.close()

# startup_event 함수 위에 이 함수 호출 코드를 추가합니다
@app.on_event("startup")
def startup_clean():
    """애플리케이션 시작 시 중복 데이터 정리"""
    clean_duplicate_data()

# 애플리케이션 시작 시 초기 데이터 삽입
@app.on_event("startup")
def startup_event():
    """애플리케이션 시작 시 국회의원 데이터를 확인하고 필요한 경우에만 API에서 불러옴"""
    db = next(get_db())
    try:
        # 기존 데이터 확인
        existing_count = db.query(MemberModel).count()
        
        # 이미 적절한 수의 데이터가 있으면 API 호출 건너뛰기
        # 실제 국회의원 수에 맞게 숫자 조정 (여기서는 300명으로 가정)
        if 280 <= existing_count <= 320:  # 약간의 여유를 두고 확인
            logger.info(f"이미 {existing_count}명의 국회의원 데이터가 DB에 존재합니다. API 호출을 건너뜁니다.")
            return
            
        # 데이터 동기화가 필요한 경우, 기존 데이터를 모두 삭제하고 새로 추가
        if existing_count > 0:
            logger.info(f"기존 {existing_count}명의 국회의원 데이터를 삭제하고 새로 불러옵니다.")
            db.query(MemberModel).delete()
            db.commit()
            
        # 데이터가 없는 경우에만 API 호출
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
            asyncio.run(sync_member_bills(db))
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
            bills_count = db.query(BillModel).count()
            
            if bills_count < 100:
                # 데이터가 적은 경우 - 전체 동기화
                logger.info(f"의안 데이터 부족 (현재 {bills_count}개). 전체 동기화를 시작합니다.")
                await sync_bills_data(db, max_pages=20, incremental=False, fetch_content=True)
            else:
                # 데이터가 이미 있는 경우 - 증분 동기화만 수행
                logger.info(f"의안 데이터가 있습니다 (현재 {bills_count}개). 증분 동기화를 시작합니다.")
                await sync_bills_data(db, max_pages=5, incremental=True, fetch_content=True)
                
            logger.info("서버 시작 시 의안 데이터 동기화 완료")
            
        except Exception as e:
            logger.error(f"의안 데이터 동기화 중 오류: {e}")
        finally:
            db.close()
            
        bills_sync_completed = True
    finally:
        bills_sync_in_progress = False

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
        # 국회의원이 대표발의한 법안 목록 조회 (최근 5개)
        bills = db.query(BillModel)\
            .filter(BillModel.rep_proposer == member.name)\
            .order_by(BillModel.proposal_date.desc())\
            .limit(5).all()
            
        # DB에 발의안이 없으면 API에서 조회 시도
        if not bills:
            try:
                # 여기에 의원별 발의안 조회 API 호출 로직 추가 (해당 API가 있으면)
                # 예시로 가정 (실제로는 API를 확인하여 수정 필요)
                pass
            except Exception as e:
                logger.error(f"의원 발의안 API 조회 중 오류: {e}")
        
        # 국회의원 발언 목록 가져오기 (API 호출) - 기존 코드 유지
        speech_data = []
        try:
            speech_records = assembly_api.get_speech_records(member_name=member.name)
            speech_data = speech_records[:5] if len(speech_records) > 0 else []
            logger.info(f"{member.name} 의원의 발언 데이터 {len(speech_data)}개 조회 성공")
        except Exception as e:
            logger.error(f"발언 데이터 조회 중 오류: {e}")
            speech_data = []
        
        # 발언 데이터 포맷팅
        speeches = []
        for speech in speech_data:
            speeches.append({
                "meeting_type": speech.get("TITLE", "본회의"),
                "date": speech.get("TAKING_DATE", ""),
                "content": speech.get("CONTENT", "발언 내용이 제공되지 않습니다.")[:100] + "...",
                "topic": speech.get("TOPIC", "일반 발언"),
                "link": speech.get("LINK_URL", "#")
            })
        
        # 활동 지표 계산 (기존 코드 유지)
        activity_data = {
            "member": {
                "bills": (member.num_bills / 50) * 100 if member.num_bills else 85,
                "attendance": member.attendance_rate if member.attendance_rate else 95,
                "speeches": (member.speech_count / 200) * 100 if member.speech_count else 90,
                "pass_rate": member.bill_pass_rate if member.bill_pass_rate else 75,
                "committee": 88
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
        # 쿼리 빌드
        query = db.query(BillModel)
        
        # 필터 적용
        if title:
            query = query.filter(BillModel.title.contains(title))
        if proposer:
            query = query.filter(BillModel.proposer.contains(proposer))
        if status:
            query = query.filter(BillModel.status == status)
        if committee:
            query = query.filter(BillModel.committee.contains(committee))
        if bill_no:
            query = query.filter(BillModel.bill_no.contains(bill_no))
            
        # 총 의안 수
        total_count = query.count()
        
        # 페이징 적용
        bills_db = query.order_by(BillModel.proposal_date.desc())\
                     .offset((page-1) * limit)\
                     .limit(limit)\
                     .all()
        
        # 의안 데이터 처리
        bills = []
        for bill in bills_db:
            bills.append({
                "id": bill.bill_id,
                "no": bill.bill_no,
                "title": bill.title,
                "proposer": bill.proposer,
                "committee": bill.committee,
                "proposal_date": bill.proposal_date,
                "status": bill.status
            })
        
        # 페이지네이션 정보 계산
        total_pages = (total_count + limit - 1) // limit  # 올림 나눗셈
        has_next = page < total_pages
        has_prev = page > 1
        
        # 페이지 버튼 범위 계산 (현재 페이지 주변 5개 페이지 표시)
        max_page_buttons = 5  # 최대 페이지 버튼 수
        half_buttons = max_page_buttons // 2
        
        if total_pages <= max_page_buttons:
            # 전체 페이지 수가 최대 버튼 수보다 적으면 모든 페이지 표시
            page_range = range(1, total_pages + 1)
        else:
            # 시작 페이지와 끝 페이지 계산
            start_page = max(1, page - half_buttons)
            end_page = min(total_pages, start_page + max_page_buttons - 1)
            
            # 끝 페이지가 최대 페이지에 도달하면 시작 페이지 재조정
            if end_page == total_pages:
                start_page = max(1, end_page - max_page_buttons + 1)
            
            page_range = range(start_page, end_page + 1)
        
        # 화면에 표시할 데이터 구성
        context = {
            "request": request,
            "bills": bills,
            "page": page,
            "limit": limit,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": has_next,
            "has_prev": has_prev,
            "page_range": page_range,  # 추가된 페이지 범위
            "title": title or "",
            "proposer": proposer or "",
            "status": status or "",
            "committee": committee or "",
            "bill_no": bill_no or ""
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
                "page_range": range(1, 2),  # 페이지 범위 기본값
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
        # DB에서 의안 정보 조회
        bill = db.query(BillModel).filter(BillModel.bill_no == bill_no).first()
        
        # DB에 없거나 내용이 비어있으면 API에서 조회
        if not bill or not bill.content:
            bill_data = assembly_api.get_bill_detail(bill_no=bill_no)
            
            if not bill_data:
                raise HTTPException(status_code=404, detail="발의안을 찾을 수 없습니다")
            
            # API에서 가져온 내용으로 DB 업데이트
            if bill and bill_data.get("DETAIL_CONTENT"):
                bill.content = bill_data.get("DETAIL_CONTENT")
                db.commit()
                logger.info(f"의안 '{bill_no}' 상세 내용 DB 업데이트 완료")
            
            # API 응답으로 상세 정보 구성
            bill_id = bill_data.get("BILL_ID", "")
            
            # 제안자 정보 조회
            proposers_info = {}
            if bill_id:
                proposers_info = assembly_api.get_bill_proposers(bill_id)
            
            # 응답 구성
            bill = {
                "id": bill_id,
                "bill_no": bill_no,
                "title": bill_data.get("BILL_NM", ""),
                "proposer": bill_data.get("PPSR_NM", ""),
                "committee": bill_data.get("JRCMIT_NM", ""),
                "proposal_date": bill_data.get("PPSL_DT", ""),
                "status": bill_data.get("RGS_CONF_RSLT", "계류"),
                "content": bill_data.get("DETAIL_CONTENT", "내용 없음"),
                "rep_proposer": proposers_info.get("rep_proposer", ""),
                "co_proposers": proposers_info.get("co_proposers", []),
                
                # 처리 경과 정보 등
                "process_history": _create_process_history(bill_data),
                "link_url": bill_data.get("LINK_URL", "")
            }
        else:
            # DB에서 조회한 경우 co_proposers가 문자열이므로 리스트로 변환
            co_proposers = bill.co_proposers.split(", ") if bill.co_proposers else []
            
            # 필요한 추가 정보 구성
            bill = {
                "id": bill.bill_id,
                "bill_no": bill.bill_no,
                "title": bill.title,
                "proposer": bill.proposer,
                "committee": bill.committee,
                "proposal_date": bill.proposal_date,
                "status": bill.status,
                "content": bill.content or "내용 없음",
                "rep_proposer": bill.rep_proposer,
                "co_proposers": co_proposers,
                
                # DB에 없는 정보는 기본값 설정
                "process_history": [],
                "link_url": f"https://likms.assembly.go.kr/bill/billDetail.do?billId={bill.bill_id}"
            }
        
        return templates.TemplateResponse("bill_detail.html", {"request": request, "bill": bill})
    
    except HTTPException:
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

# 처리 경과 정보 생성 도우미 함수
def _create_process_history(bill_data):
    """의안 처리 경과 정보 생성"""
    process_history = []
    
    # 제안일
    if bill_data.get("PPSL_DT"):
        process_history.append({
            "date": bill_data.get("PPSL_DT"),
            "content": "발의"
        })
    
    # 소관위원회 회부일
    if bill_data.get("JRCMIT_CMMT_DT"):
        process_history.append({
            "date": bill_data.get("JRCMIT_CMMT_DT"),
            "content": f"소관위원회({bill_data.get('JRCMIT_NM', '')}) 회부"
        })
    
    # 소관위원회 상정일
    if bill_data.get("JRCMIT_PRSNT_DT"):
        process_history.append({
            "date": bill_data.get("JRCMIT_PRSNT_DT"),
            "content": "소관위원회 상정"
        })
    
    # 소관위원회 처리일
    if bill_data.get("JRCMIT_PROC_DT"):
        process_history.append({
            "date": bill_data.get("JRCMIT_PROC_DT"),
            "content": f"소관위원회 의결: {bill_data.get('JRCMIT_PROC_RSLT', '')}"
        })
    
    # 법사위 회부일
    if bill_data.get("LAW_CMMT_DT"):
        process_history.append({
            "date": bill_data.get("LAW_CMMT_DT"),
            "content": "법제사법위원회 회부"
        })
    
    # 본회의 의결일
    if bill_data.get("RGS_RSLN_DT"):
        process_history.append({
            "date": bill_data.get("RGS_RSLN_DT"),
            "content": f"본회의 의결: {bill_data.get('RGS_CONF_RSLT', '')}"
        })
    
    # 처리 경과 정보 날짜순 정렬
    return sorted(process_history, key=lambda x: x["date"])

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

@app.get("/admin/sync-bills", response_class=HTMLResponse)
async def sync_bills(request: Request, db: Session = Depends(get_db), assembly_term: int = 22):
    """국회 의안 데이터를 API에서 가져와 DB에 동기화하는 관리자 페이지"""
    result = {"success": False, "message": "", "count": 0}
    
    try:
        # API 키 확인
        api_key = settings.ASSEMBLY_API_KEY
        if not api_key or api_key == "":
            result["message"] = "API 키가 설정되지 않았습니다. .env 파일을 확인하세요."
            return templates.TemplateResponse(
                "admin/sync_data.html", 
                {"request": request, "result": result}
            )
        
        # 의안 데이터 동기화
        total_bills = await sync_bills_data(db)
        
        result["success"] = True
        result["message"] = "의안 데이터 동기화 완료"
        result["count"] = total_bills
        
    except Exception as e:
        result["message"] = f"오류 발생: {str(e)}"
        logger.error(f"의안 동기화 중 오류: {e}")
    
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

# 애플리케이션 종료 시 스케줄러 종료
@app.on_event("shutdown")
def shutdown_scheduler():
    """애플리케이션 종료 시 스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

# 라우트 추가: 필요시 확장 (발의안, 검색 등)
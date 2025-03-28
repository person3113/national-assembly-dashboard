"""
국회의원 데이터를 관리하고 동기화하는 서비스 모듈

이 모듈은 국회의원 정보를 외부 API에서 조회하여 데이터베이스에 저장하고 관리하는 기능을 제공합니다.
"""
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel
from app.services.assembly_api import assembly_api
from app.utils.helpers import parse_date, calculate_activity_score

logger = logging.getLogger(__name__)

def sync_members_from_api(db: Session, assembly_term: int = 22) -> int:
    """
    국회의원 정보를 API에서 조회하여 데이터베이스에 저장

    Args:
        db: 데이터베이스 세션
        assembly_term: 국회 대수 (기본값: 22)

    Returns:
        int: 추가/업데이트된 국회의원 수
    """
    try:
        logger.info(f"{assembly_term}대 국회의원 정보 동기화 시작...")
        
        # API에서 국회의원 목록 조회
        members_data = assembly_api.get_members(assembly_term=assembly_term)
        
        if not members_data:
            logger.warning("API에서 국회의원 정보를 가져오지 못했습니다.")
            return 0
            
        # API 데이터 추가
        member_count = 0
        for member_data in members_data:
            try:
                # 생년월일 변환
                birth_date = None
                if member_data.get("BTH_DATE"):
                    birth_date = parse_date(member_data.get("BTH_DATE"))
                
                # 이미 존재하는 의원인지 확인
                existing_member = db.query(MemberModel).filter(
                    MemberModel.name == member_data.get("HG_NM", "")
                ).first()
                
                if existing_member:
                    # 기존 의원 정보 업데이트
                    existing_member.party = member_data.get("POLY_NM", existing_member.party)
                    existing_member.district = member_data.get("ORIG_NM", existing_member.district)
                    existing_member.position = member_data.get("JOB_RES_NM", existing_member.position)
                    existing_member.committee = member_data.get("CMIT_NM", existing_member.committee)
                    existing_member.committees = member_data.get("CMITS", existing_member.committees)
                    existing_member.tel_no = member_data.get("TEL_NO", existing_member.tel_no)
                    existing_member.email = member_data.get("E_MAIL", existing_member.email)
                    existing_member.homepage = member_data.get("HOMEPAGE", existing_member.homepage)
                    existing_member.last_updated = datetime.now().date()
                    
                    logger.debug(f"국회의원 {existing_member.name} 정보 업데이트")
                else:
                    # 새 국회의원 데이터 생성
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
                    logger.debug(f"새 국회의원 {new_member.name} 추가")
                
                member_count += 1
            except Exception as e:
                logger.error(f"국회의원 데이터 처리 중 오류: {e}")
        
        # 커밋
        db.commit()
        logger.info(f"총 {member_count}명의 국회의원 정보를 처리했습니다.")
        
        # 활동 점수 업데이트
        update_activity_scores(db)
        
        return member_count
    except Exception as e:
        db.rollback()
        logger.error(f"국회의원 정보 동기화 중 오류: {e}")
        return 0

async def sync_member_bills(db: Session) -> int:
    """
    국회의원별 발의안 정보를 API에서 가져와 DB에 저장

    Args:
        db: 데이터베이스 세션

    Returns:
        int: 처리된 발의안 수
    """
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
                # API 호출 방식 수정 - PPSR_NM 파라미터 사용
                bills_data = []
                
                # 모든 국회의원에게 발의안이 없을 수 있으므로 에러 발생 시에도 진행
                try:
                    # 22대 국회 시작일부터 현재까지 기간 설정
                    start_date = "20240530"  # 22대 국회 시작일
                    end_date = datetime.now().strftime("%Y%m%d")
                    
                    # API 호출 - 의원 이름으로 검색
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
                            bill_id=bill_data.get("BILL_ID", ""),
                            bill_no=bill_data.get("BILL_NO", ""),
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
            
            # API 호출 간 지연
            time.sleep(0.5)
        
        # 모든 국회의원 처리 후 커밋
        db.commit()
        logger.info(f"국회의원 발의안 정보 동기화 완료. 총 {total_bills}개 발의안 처리됨.")
        
        return total_bills
    except Exception as e:
        db.rollback()
        logger.error(f"발의안 정보 동기화 중 오류 발생: {e}")
        return 0

def update_activity_scores(db: Session) -> int:
    """
    모든 국회의원의 활동 점수를 계산하여 업데이트

    Args:
        db: 데이터베이스 세션

    Returns:
        int: 업데이트된 국회의원 수
    """
    try:
        members = db.query(MemberModel).all()
        count = 0
        
        for member in members:
            try:
                # 활동 점수 계산 및 업데이트
                member.activity_score = calculate_activity_score(member)
                count += 1
            except Exception as e:
                logger.error(f"{member.name} 의원의 활동 점수 계산 중 오류: {e}")
        
        db.commit()
        logger.info(f"총 {count}명의 국회의원 활동 점수를 업데이트했습니다.")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"활동 점수 업데이트 중 오류: {e}")
        return 0
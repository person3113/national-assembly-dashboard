"""
의안 데이터를 관리하고 동기화하는 서비스 모듈

이 모듈은 국회 의안 정보를 외부 API에서 조회하여 데이터베이스에 저장하고 관리하는 기능을 제공합니다.
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.bill import Bill as BillModel
from app.models.member import Member as MemberModel
from app.services.assembly_api import assembly_api
from app.utils.helpers import parse_date

logger = logging.getLogger(__name__)

async def sync_bills_data(
    db: Session, 
    max_pages: int = 10, 
    update_existing: bool = False, 
    incremental: bool = True, 
    fetch_content: bool = True
) -> int:
    """
    의안 데이터를 API에서 가져와 DB에 동기화하는 비동기 함수
    
    Args:
        db: 데이터베이스 세션
        max_pages: 처리할 최대 페이지 수
        update_existing: 기존 의안 정보도 업데이트할지 여부
        incremental: 증분 업데이트 여부 (최근 의안만 가져올지)
        fetch_content: 의안 상세 내용을 가져올지 여부
        
    Returns:
        int: 추가된 신규 의안 수
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

                    # 제안자명 정제
                    if rep_proposer:
                        clean_name = rep_proposer
                        for suffix in ["의원", "위원장", "위원회"]:
                            clean_name = clean_name.replace(suffix, "").strip()
                        new_bill.proposer_clean = clean_name
                    
                    # 대표 발의자가 있으면 의원 테이블에서 조회하여 연결
                    if rep_proposer and "위원장" not in rep_proposer and rep_proposer != "정부":
                        # 정제된 이름으로 조회
                        clean_name = new_bill.proposer_clean if new_bill.proposer_clean else rep_proposer.replace("의원", "").strip()
                        
                        proposer_member = db.query(MemberModel).filter(
                            MemberModel.name == clean_name
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
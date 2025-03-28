"""
애플리케이션에서 공통으로 사용하는 유틸리티 함수들을 모아놓은 모듈
"""
import logging
import pprint
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel

logger = logging.getLogger(__name__)

def pprint_filter(context, value):
    """
    템플릿에서 사용할 Pretty Print 필터
    
    Args:
        context: Jinja2 컨텍스트
        value: 출력할 값
        
    Returns:
        str: 포맷팅된 문자열
    """
    return pprint.pformat(value)

def calculate_activity_score(member: MemberModel) -> float:
    """
    국회의원의 활동 점수를 계산하는 함수
    
    가중치:
    - 발의안 수: 40%
    - 출석률: 30%
    - 발언 횟수: 20%
    - 법안통과율: 10%
    
    Args:
        member: 국회의원 모델 객체
        
    Returns:
        float: 계산된 활동 점수 (0-100)
    """
    # Member 모델의 메서드 호출
    return member.calculate_activity_score()

def clean_duplicate_members(db: Session) -> int:
    """
    중복된 국회의원 데이터를 제거하는 함수
    
    Args:
        db: 데이터베이스 세션
        
    Returns:
        int: 제거된 중복 레코드 수
    """
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
        removed_count = total_count - final_count
        logger.info(f"총 {removed_count}개의 중복 데이터가 제거되었습니다.")
        
        return removed_count
    except Exception as e:
        db.rollback()
        logger.error(f"중복 데이터 정리 중 오류 발생: {e}")
        return 0

def create_process_history(bill_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    의안 처리 경과 정보를 생성하는 함수
    
    Args:
        bill_data: API에서 받아온 의안 데이터
        
    Returns:
        List[Dict[str, str]]: 날짜와 내용으로 구성된 처리 경과 목록
    """
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

def calculate_pagination_range(page: int, total_pages: int, max_buttons: int = 5) -> List[int]:
    """
    페이지네이션 범위를 계산하는 함수
    
    Args:
        page: 현재 페이지 번호
        total_pages: 전체 페이지 수
        max_buttons: 표시할 최대 버튼 수 (기본값: 5)
        
    Returns:
        List[int]: 표시할 페이지 번호 목록
    """
    half_buttons = max_buttons // 2
    
    if total_pages <= max_buttons:
        # 전체 페이지 수가 최대 버튼 수보다 적으면 모든 페이지 표시
        return list(range(1, total_pages + 1))
    else:
        # 시작 페이지와 끝 페이지 계산
        start_page = max(1, page - half_buttons)
        end_page = min(total_pages, start_page + max_buttons - 1)
        
        # 끝 페이지가 최대 페이지에 도달하면 시작 페이지 재조정
        if end_page == total_pages:
            start_page = max(1, end_page - max_buttons + 1)
        
        return list(range(start_page, end_page + 1))

def parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """
    다양한 형식의 날짜 문자열을 datetime.date 객체로 변환
    
    Args:
        date_str: 날짜 문자열 (YYYY-MM-DD, YYYYMMDD 등)
        
    Returns:
        datetime.date: 변환된 날짜 객체
    """
    if not date_str:
        return None
    
    try:
        # YYYY-MM-DD 형식 처리
        if "-" in date_str:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        # YYYYMMDD 형식 처리
        elif len(date_str) == 8:
            return datetime.strptime(date_str, "%Y%m%d").date()
        else:
            logger.warning(f"지원하지 않는 날짜 형식: {date_str}")
            return None
    except (ValueError, TypeError) as e:
        logger.warning(f"날짜 변환 오류 ({date_str}): {e}")
        return None
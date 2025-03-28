"""
발의안 관련 웹 페이지 라우트 핸들러 모듈

발의안 목록, 상세 정보 등의 웹 페이지 요청을 처리합니다.
"""
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.bill import Bill as BillModel
from app.services.assembly_api import assembly_api
from app.utils.helpers import calculate_pagination_range, create_process_history

# 로거 설정
logger = logging.getLogger(__name__)

# 라우터 생성
router = APIRouter()

# 템플릿 설정 (main.py에서 설정한 templates 객체를 가져와야 합니다)
templates = None

def init_templates(templates_instance):
    """템플릿 인스턴스 설정"""
    global templates
    templates = templates_instance

@router.get("/bills", response_class=HTMLResponse)
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
    """
    발의안 목록 페이지
    
    Args:
        request: 요청 객체
        db: 데이터베이스 세션
        title: 제목 검색어 (선택)
        proposer: 제안자 검색어 (선택)
        status: 처리 상태 필터 (선택)
        committee: 소관위원회 필터 (선택)
        bill_no: 의안번호 검색어 (선택)
        page: 페이지 번호 (기본값: 1)
        limit: 페이지당 항목 수 (기본값: 20)
    
    Returns:
        HTMLResponse: 발의안 목록 페이지 HTML
    """
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
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1  # 올림 나눗셈
        has_next = page < total_pages
        has_prev = page > 1
        
        # 페이지 버튼 범위 계산
        page_range = calculate_pagination_range(page, total_pages)
        
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
            "page_range": page_range,
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

@router.get("/bills/{bill_no}", response_class=HTMLResponse)
async def bill_detail_page(
    request: Request,
    bill_no: str,
    db: Session = Depends(get_db)
):
    """
    발의안 상세 페이지
    
    Args:
        request: 요청 객체
        bill_no: 의안번호
        db: 데이터베이스 세션
    
    Returns:
        HTMLResponse: 발의안 상세 페이지 HTML
    """
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

            # API 응답 구조 로깅
            logger.info(f"발의안 API 응답 필드: {list(bill_data.keys())}")

            # 발의자 정보를 다양한 필드에서 찾기
            proposer_info = ""
            possible_fields = ["PPSR_CN", "PPSR_NM", "PROPOSER", "PRESENTER", "BILL_PRESENTER"]
            for field in possible_fields:
                if field in bill_data and bill_data[field]:
                    proposer_info = bill_data[field]
                    logger.info(f"발의자 정보 필드 '{field}' 사용: {proposer_info}")
                    break

            # 응답 구성
            bill = {
                "id": bill_id,
                "bill_no": bill_no,
                "title": bill_data.get("BILL_NM", ""),
                "proposer": proposer_info,  # 위에서 찾은 발의자 정보
                "committee": bill_data.get("JRCMIT_NM", ""),
                "proposal_date": bill_data.get("PPSL_DT", ""),
                "status": bill_data.get("RGS_CONF_RSLT", "계류"),
                "content": bill_data.get("DETAIL_CONTENT", "내용 없음"),
                "rep_proposer": proposers_info.get("rep_proposer", ""),
                "co_proposers": proposers_info.get("co_proposers", []),
                
                # 처리 경과 정보 등
                "process_history": create_process_history(bill_data),
                "link_url": bill_data.get("LINK_URL", "")
            }
        else:
            # DB에서 조회한 경우 co_proposers가 문자열이므로 리스트로 변환
            co_proposers = bill.co_proposers.split(", ") if bill.co_proposers else []
            
            # 발의자 정보 구성
            proposer_info = ""
            if bill.co_proposers:
                # co_proposers가 있으면 "대표발의자 등 X인" 형식으로 생성
                if bill.rep_proposer:
                    proposer_count = len(co_proposers) + 1  # 대표발의자 포함
                    proposer_info = f"{bill.rep_proposer}의원 등 {proposer_count}인"
                else:
                    proposer_info = bill.proposer or "정보 없음"
            else:
                proposer_info = bill.proposer or "정보 없음"
            
            # 필요한 추가 정보 구성
            bill = {
                "id": bill.bill_id,
                "bill_no": bill.bill_no,
                "title": bill.title,
                "proposer": proposer_info,  # 발의자 정보 설정
                "committee": bill.committee,
                "proposal_date": bill.proposal_date,
                "status": bill.status,
                "content": bill.content or "내용 없음",
                "rep_proposer": bill.rep_proposer,
                "co_proposers": co_proposers,
                
                # DB에 없는 정보는 기본값 설정
                "process_history": bill.get_process_history() if hasattr(bill, 'get_process_history') else [],
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
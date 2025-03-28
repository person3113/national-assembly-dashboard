"""
국회의원 관련 웹 페이지 라우트 핸들러 모듈

국회의원 목록, 상세 정보, 랭킹 등의 웹 페이지 요청을 처리합니다.
"""
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db.session import get_db
from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel
from app.utils.helpers import calculate_pagination_range

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

@router.get("/members", response_class=HTMLResponse)
async def members_page(
    request: Request,
    db: Session = Depends(get_db),
    name: Optional[str] = None,
    party: Optional[str] = None,
    district: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    """
    국회의원 목록 페이지
    
    Args:
        request: 요청 객체
        db: 데이터베이스 세션
        name: 이름 검색어 (선택)
        party: 정당 검색어 (선택)
        district: 지역구 검색어 (선택)
        page: 페이지 번호 (기본값: 1)
        limit: 페이지당 항목 수 (기본값: 20)
    
    Returns:
        HTMLResponse: 국회의원 목록 페이지 HTML
    """
    try:
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
        total_pages = (total + limit - 1) // limit if total > 0 else 1
        
        # 페이지 범위 검증
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        
        # 오프셋 계산 및 데이터 조회
        offset = (page - 1) * limit
        members = query.offset(offset).limit(limit).all()
        
        # 페이지네이션 범위 계산
        page_range = calculate_pagination_range(page, total_pages)
        
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
    except Exception as e:
        logger.error(f"국회의원 목록 조회 중 오류: {e}")
        return templates.TemplateResponse(
            "members.html",
            {
                "request": request,
                "members": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "total_pages": 1,
                "page_range": [1],
                "name": name or "",
                "party": party or "",
                "district": district or "",
                "error_message": "국회의원 정보를 불러오는 중 오류가 발생했습니다."
            }
        )

@router.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail_page(
    request: Request,
    member_id: int,
    db: Session = Depends(get_db)
):
    """
    국회의원 상세 정보 페이지
    
    Args:
        request: 요청 객체
        member_id: 국회의원 ID
        db: 데이터베이스 세션
    
    Returns:
        HTMLResponse: 국회의원 상세 정보 페이지 HTML
    
    Raises:
        HTTPException: 국회의원을 찾을 수 없는 경우
    """
    try:
        # 특정 국회의원 조회
        member = db.query(MemberModel).filter(MemberModel.id == member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="국회의원을 찾을 수 없습니다")
        
        # 추가 데이터 수집
        try:
            # 국회의원이 대표발의한 법안 목록 조회 (최근 5개)
            bills = db.query(BillModel)\
                .filter(
                    # 1) 대표발의자 이름이 의원 이름과 일치하거나
                    (BillModel.rep_proposer == member.name) |
                    # 2) 대표발의자 이름이 "의원"이 붙은 형태와 일치하거나
                    (BillModel.rep_proposer == member.name + "의원") |
                    # 3) 제안자 이름이 의원 이름과 일치하거나
                    (BillModel.proposer == member.name) |
                    # 4) 제안자 이름이 "의원"이 붙은 형태와 일치
                    (BillModel.proposer == member.name + "의원")
                )\
                .order_by(BillModel.proposal_date.desc())\
                .limit(5).all()
            
            # 활동 지표 계산
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
            
    except HTTPException:
        raise  # HTTP 예외는 그대로 전달
    except Exception as e:
        logger.error(f"국회의원 상세 정보 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다")

@router.get("/rankings", response_class=HTMLResponse)
async def rankings_page(
    request: Request,
    db: Session = Depends(get_db),
    category: str = "activity",  # 'activity', 'bills', 'speeches', 'attendance'
    party: Optional[str] = None,
    limit: int = 20
):
    """
    국회의원 활동 랭킹 페이지
    
    Args:
        request: 요청 객체
        db: 데이터베이스 세션
        category: 랭킹 기준 카테고리 (기본값: "activity")
        party: 정당 필터 (선택)
        limit: 표시할 의원 수 (기본값: 20)
    
    Returns:
        HTMLResponse: 국회의원 랭킹 페이지 HTML
    """
    try:
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
        
        # 정당별 평균 계산
        party_averages = {}
        parties = db.query(MemberModel.party).distinct().all()
        
        for party_row in parties:
            party_name = party_row[0]
            if not party_name:  # 정당명이 없는 경우 스킵
                continue
                
            # 해당 정당 의원들의 평균 계산
            if category == "bills":
                avg = db.query(func.avg(MemberModel.num_bills)).filter(MemberModel.party == party_name).scalar() or 0
            elif category == "speeches":
                avg = db.query(func.avg(MemberModel.speech_count)).filter(MemberModel.party == party_name).scalar() or 0
            elif category == "attendance":
                avg = db.query(func.avg(MemberModel.attendance_rate)).filter(MemberModel.party == party_name).scalar() or 0
            else:  # activity
                avg = db.query(func.avg(MemberModel.activity_score)).filter(MemberModel.party == party_name).scalar() or 0
                
            party_averages[party_name] = round(float(avg), 1)
        
        # 전체 평균 계산
        if category == "bills":
            total_avg = db.query(func.avg(MemberModel.num_bills)).scalar() or 0
        elif category == "speeches":
            total_avg = db.query(func.avg(MemberModel.speech_count)).scalar() or 0
        elif category == "attendance":
            total_avg = db.query(func.avg(MemberModel.attendance_rate)).scalar() or 0
        else:  # activity
            total_avg = db.query(func.avg(MemberModel.activity_score)).scalar() or 0
        
        # 최대값과 최소값 찾기
        if category == "bills":
            max_record = db.query(MemberModel).order_by(MemberModel.num_bills.desc()).first()
            min_record = db.query(MemberModel).filter(MemberModel.num_bills > 0).order_by(MemberModel.num_bills).first()
            max_value = max_record.num_bills if max_record else 0
            min_value = min_record.num_bills if min_record else 0
            max_name = max_record.name if max_record else ""
            min_name = min_record.name if min_record else ""
        elif category == "speeches":
            max_record = db.query(MemberModel).order_by(MemberModel.speech_count.desc()).first()
            min_record = db.query(MemberModel).filter(MemberModel.speech_count > 0).order_by(MemberModel.speech_count).first()
            max_value = max_record.speech_count if max_record else 0
            min_value = min_record.speech_count if min_record else 0
            max_name = max_record.name if max_record else ""
            min_name = min_record.name if min_record else ""
        elif category == "attendance":
            max_record = db.query(MemberModel).order_by(MemberModel.attendance_rate.desc()).first()
            min_record = db.query(MemberModel).filter(MemberModel.attendance_rate > 0).order_by(MemberModel.attendance_rate).first()
            max_value = max_record.attendance_rate if max_record else 0
            min_value = min_record.attendance_rate if min_record else 0
            max_name = max_record.name if max_record else ""
            min_name = min_record.name if min_record else ""
        else:  # activity
            max_record = db.query(MemberModel).order_by(MemberModel.activity_score.desc()).first()
            min_record = db.query(MemberModel).filter(MemberModel.activity_score > 0).order_by(MemberModel.activity_score).first()
            max_value = max_record.activity_score if max_record else 0
            min_value = min_record.activity_score if min_record else 0
            max_name = max_record.name if max_record else ""
            min_name = min_record.name if min_record else ""
        
        # 상위 10% 평균 계산
        total_count = db.query(MemberModel).count()
        top_10_percent_count = max(1, int(total_count * 0.1))  # 최소 1명
        
        if category == "bills":
            top_members = db.query(MemberModel).order_by(MemberModel.num_bills.desc()).limit(top_10_percent_count).all()
            top_avg = sum(m.num_bills for m in top_members) / len(top_members) if top_members else 0
        elif category == "speeches":
            top_members = db.query(MemberModel).order_by(MemberModel.speech_count.desc()).limit(top_10_percent_count).all()
            top_avg = sum(m.speech_count for m in top_members) / len(top_members) if top_members else 0
        elif category == "attendance":
            top_members = db.query(MemberModel).order_by(MemberModel.attendance_rate.desc()).limit(top_10_percent_count).all()
            top_avg = sum(m.attendance_rate for m in top_members) / len(top_members) if top_members else 0
        else:  # activity
            top_members = db.query(MemberModel).order_by(MemberModel.activity_score.desc()).limit(top_10_percent_count).all()
            top_avg = sum(m.activity_score for m in top_members) / len(top_members) if top_members else 0
        
        stats = {
            'total_avg': round(float(total_avg), 1),
            'max_value': round(float(max_value), 1),
            'max_name': max_name,
            'min_value': round(float(min_value), 1),
            'min_name': min_name,
            'top_avg': round(float(top_avg), 1)
        }
        
        return templates.TemplateResponse(
            "rankings.html", 
            {
                "request": request,
                "members": members,
                "category": category,
                "party": party,
                "limit": limit,
                "party_averages": party_averages,
                "stats": stats
            }
        )
        
    except Exception as e:
        logger.error(f"랭킹 페이지 처리 중 오류: {e}")
        return templates.TemplateResponse(
            "rankings.html", 
            {
                "request": request,
                "members": [],
                "category": category,
                "party": party,
                "limit": limit,
                "party_averages": {},
                "stats": {
                    'total_avg': 0,
                    'max_value': 0,
                    'max_name': '',
                    'min_value': 0,
                    'min_name': '',
                    'top_avg': 0
                },
                "error_message": "랭킹 데이터를 불러오는 중 오류가 발생했습니다."
            }
        )
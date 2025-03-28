"""
대시보드 메인 페이지 관련 라우트 핸들러 모듈

홈 페이지, 검색 등의 메인 기능 웹 페이지 요청을 처리합니다.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db.session import get_db
from app.models.member import Member as MemberModel
from app.models.bill import Bill as BillModel

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

@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    """
    대시보드 홈 페이지
    
    Args:
        request: 요청 객체
        db: 데이터베이스 세션
    
    Returns:
        HTMLResponse: 홈 페이지 HTML
    """
    try:
        # 활동 점수 상위 10명의 국회의원 조회
        top_members = db.query(MemberModel).order_by(MemberModel.activity_score.desc()).limit(10).all()
        
        # 정당별 의원 수 조회
        party_counts = db.query(
            MemberModel.party, 
            func.count(MemberModel.id).label('count')
        ).group_by(MemberModel.party).all()
        
        # 정당별 의원 수를 차트용 데이터로 변환
        party_data = {
            'labels': [party[0] for party in party_counts if party[0]],  # 빈 문자열 제외
            'counts': [party[1] for party in party_counts if party[0]]   # 빈 문자열 제외
        }
        
        # 최근 발의안 5개 조회
        recent_bills = db.query(BillModel).order_by(BillModel.proposal_date.desc()).limit(5).all()
        
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                "top_members": top_members,
                "party_data": party_data,
                "recent_bills": recent_bills
            }
        )
    except Exception as e:
        logger.error(f"홈 페이지 처리 중 오류: {e}")
        # 오류 발생 시 기본 데이터 제공
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                "top_members": [],
                "party_data": {"labels": [], "counts": []},
                "recent_bills": [],
                "error_message": "데이터를 불러오는 중 오류가 발생했습니다."
            }
        )

@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request, 
    db: Session = Depends(get_db),
    q: Optional[str] = None
):
    """
    통합 검색 페이지
    
    Args:
        request: 요청 객체
        db: 데이터베이스 세션
        q: 검색어
    
    Returns:
        HTMLResponse: 검색 결과 페이지 HTML
    """
    try:
        if not q:
            return templates.TemplateResponse(
                "search.html", 
                {
                    "request": request,
                    "query": "",
                    "members": [],
                    "bills": [],
                    "total_members": 0,
                    "total_bills": 0
                }
            )
        
        # 국회의원 검색
        members = db.query(MemberModel)\
            .filter(MemberModel.name.contains(q))\
            .order_by(MemberModel.activity_score.desc())\
            .limit(10)\
            .all()
        
        total_members = db.query(MemberModel)\
            .filter(MemberModel.name.contains(q))\
            .count()
        
        # 발의안 검색
        bills = db.query(BillModel)\
            .filter(
                BillModel.title.contains(q) | 
                BillModel.content.contains(q) |
                BillModel.proposer.contains(q)
            )\
            .order_by(BillModel.proposal_date.desc())\
            .limit(10)\
            .all()
        
        total_bills = db.query(BillModel)\
            .filter(
                BillModel.title.contains(q) | 
                BillModel.content.contains(q) |
                BillModel.proposer.contains(q)
            )\
            .count()
        
        return templates.TemplateResponse(
            "search.html", 
            {
                "request": request,
                "query": q,
                "members": members,
                "bills": bills,
                "total_members": total_members,
                "total_bills": total_bills
            }
        )
    except Exception as e:
        logger.error(f"검색 처리 중 오류: {e}")
        return templates.TemplateResponse(
            "search.html", 
            {
                "request": request,
                "query": q or "",
                "members": [],
                "bills": [],
                "total_members": 0,
                "total_bills": 0,
                "error_message": "검색 중 오류가 발생했습니다."
            }
        )

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """
    서비스 소개 페이지
    
    Args:
        request: 요청 객체
    
    Returns:
        HTMLResponse: 소개 페이지 HTML
    """
    return templates.TemplateResponse(
        "about.html", 
        {
            "request": request
        }
    )
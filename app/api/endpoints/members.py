from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.member import Member as MemberModel
from app.schemas.member import Member, MemberRanking
from app.services.assembly_api import assembly_api

router = APIRouter()

@router.get("/", response_model=List[Member])
def get_members(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    name: Optional[str] = None,
    party: Optional[str] = None,
    district: Optional[str] = None
):
    """
    국회의원 목록을 조회합니다.
    필터링 옵션: 이름, 정당, 선거구
    """
    query = db.query(MemberModel)
    
    # 필터링 조건 적용
    if name:
        query = query.filter(MemberModel.name.contains(name))
    if party:
        query = query.filter(MemberModel.party == party)
    if district:
        query = query.filter(MemberModel.district == district)
    
    # 페이징 적용
    members = query.offset(skip).limit(limit).all()
    return members

@router.get("/ranking", response_model=List[MemberRanking])
def get_member_rankings(
    db: Session = Depends(get_db),
    limit: int = 20,
    party: Optional[str] = None
):
    """
    국회의원 활동 점수 랭킹을 조회합니다.
    필터링 옵션: 정당
    """
    query = db.query(MemberModel)
    
    # 정당 필터링 조건 적용
    if party:
        query = query.filter(MemberModel.party == party)
    
    # 활동 점수 내림차순으로 정렬
    members = query.order_by(MemberModel.activity_score.desc()).limit(limit).all()
    
    # 랭킹 정보 생성
    result = []
    for i, member in enumerate(members):
        result.append(
            MemberRanking(
                id=member.id,
                name=member.name,
                party=member.party,
                district=member.district,
                activity_score=member.activity_score,
                rank=i + 1
            )
        )
    
    return result

@router.get("/sync-from-api")
def sync_members_from_api(
    db: Session = Depends(get_db),
    assembly_term: int = 22,
):
    """
    국회정보 API에서 국회의원 정보를 가져와 데이터베이스에 동기화합니다.
    """
    try:
        # API에서 국회의원 목록 조회
        members_data = assembly_api.get_members(assembly_term=assembly_term)
        
        # 데이터베이스에 저장
        for member_data in members_data:
            # 이미 존재하는 국회의원인지 확인
            existing_member = db.query(MemberModel).filter(
                MemberModel.name == member_data.get("HG_NM", "")  # HG_NM: 이름
            ).first()
            
            if existing_member:
                # 기존 데이터 업데이트
                existing_member.party = member_data.get("POLY_NM", "")  # POLY_NM: 정당명
                existing_member.district = member_data.get("ORIG_NM", "")  # ORIG_NM: 선거구
                existing_member.position = member_data.get("CURR_COMMITTEE", "")  # CURR_COMMITTEE: 소속위원회
                existing_member.last_updated = datetime.now().date()
            else:
                # 새 국회의원 데이터 생성
                new_member = MemberModel(
                    name=member_data.get("HG_NM", ""),  # 이름
                    hanja_name=member_data.get("HJ_NM", ""),  # 한자명
                    eng_name=member_data.get("ENG_NM", ""),  # 영문명
                    party=member_data.get("POLY_NM", ""),  # 정당명
                    district=member_data.get("ORIG_NM", ""),  # 선거구
                    position=member_data.get("CURR_COMMITTEE", ""),  # 소속위원회
                )
                db.add(new_member)
        
        db.commit()
        return {"message": "국회의원 정보 동기화 완료", "count": len(members_data)}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"동기화 오류: {str(e)}")
from datetime import date
from typing import Optional
from pydantic import BaseModel

class MemberBase(BaseModel):
    name: str
    party: Optional[str] = None
    district: Optional[str] = None

class MemberCreate(MemberBase):
    hanja_name: Optional[str] = None
    eng_name: Optional[str] = None
    birth_date: Optional[date] = None
    position: Optional[str] = None

class MemberUpdate(BaseModel):
    name: Optional[str] = None
    hanja_name: Optional[str] = None
    eng_name: Optional[str] = None
    birth_date: Optional[date] = None
    position: Optional[str] = None
    party: Optional[str] = None
    district: Optional[str] = None
    num_bills: Optional[int] = None
    attendance_rate: Optional[float] = None
    speech_count: Optional[int] = None
    activity_score: Optional[float] = None
    is_active: Optional[bool] = None
    last_updated: Optional[date] = None

class Member(MemberBase):
    id: int
    hanja_name: Optional[str] = None
    eng_name: Optional[str] = None
    birth_date: Optional[date] = None
    position: Optional[str] = None
    num_bills: int = 0
    attendance_rate: float = 0.0
    speech_count: int = 0
    activity_score: float = 0.0
    is_active: bool = True
    last_updated: Optional[date] = None

    class Config:
        # orm_mode = True
        from_attributes = True  # Update this line

class MemberRanking(BaseModel):
    id: int
    name: str
    party: Optional[str] = None
    district: Optional[str] = None
    activity_score: float
    rank: int
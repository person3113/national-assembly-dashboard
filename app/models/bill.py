from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    proposer = Column(String, index=True)  # 발의자
    status = Column(String, index=True)  # 처리 상태
    committee = Column(String, index=True)  # 소관 위원회
    proposal_date = Column(Date)  # 발의일
    content = Column(String)  # 제안이유 및 주요내용

    # 관계 설정 (예: 발의자와의 관계)
    proposer_id = Column(Integer, ForeignKey("members.id"))
    proposer_member = relationship("Member", back_populates="bills")

# Member 모델에 bills 관계 추가
from app.models.member import Member

Member.bills = relationship("Bill", order_by=Bill.id, back_populates="proposer_member")
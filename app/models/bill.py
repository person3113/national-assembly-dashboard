from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text
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
    content = Column(Text)  # 제안이유 및 주요내용
    co_proposers = Column(String, nullable=True)  # 공동발의자 (쉼표로 구분된 문자열)

    # 관계 설정 (발의자와의 관계)
    proposer_id = Column(Integer, ForeignKey("members.id"))
    proposer_member = relationship("Member", back_populates="bills")

# Member 모델에 bills 관계 추가 - 순환 참조 방지를 위해 별도 import
from app.models.member import Member

# Member 클래스에 bills 관계 설정
Member.bills = relationship("Bill", order_by=Bill.proposal_date.desc(), back_populates="proposer_member")
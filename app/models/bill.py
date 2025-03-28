from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base
from app.models.member import Member

class Bill(Base):
    """
    국회 의안 정보를 저장하는 모델
    
    의안의 기본 정보(제목, 제안자, 상태 등)와 관련 정보(표결 결과, 법률 종류 등)를 포함
    """
    __tablename__ = "bills"

    # 기본 식별 필드
    id = Column(Integer, primary_key=True, index=True, comment="고유 ID")
    bill_id = Column(String, index=True, unique=True, comment="의안ID - BILL_ID")
    bill_no = Column(String, index=True, comment="의안번호 - BILL_NO")
    
    # 의안 기본 정보
    title = Column(String, index=True, comment="의안명")
    proposer = Column(String, index=True, comment="발의자")
    status = Column(String, index=True, comment="처리 상태")
    committee = Column(String, index=True, comment="소관 위원회")
    proposal_date = Column(Date, comment="발의일")
    content = Column(Text, comment="제안이유 및 주요내용")
    
    # 발의자 관련 정보
    co_proposers = Column(String, nullable=True, comment="공동발의자 (쉼표로 구분된 문자열)")
    rep_proposer = Column(String, nullable=True, comment="대표 발의자")
    proposer_clean = Column(String, index=True, nullable=True, comment="정제된 제안자명")
    
    # 표결 및 처리 정보
    vote_result = Column(String, nullable=True, comment="표결 결과")
    vote_date = Column(Date, nullable=True, comment="표결일")
    bill_kind = Column(String, nullable=True, comment="의안 종류")
    
    # 데이터 관리용 필드
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="최종 업데이트 일시")

    # 관계 설정 (발의자와의 관계)
    proposer_id = Column(Integer, ForeignKey("members.id"), nullable=True, comment="발의자 ID (외래키)")
    proposer_member = relationship("Member")
    
    def __repr__(self):
        """객체 문자열 표현"""
        return f"<Bill(id={self.id}, bill_no='{self.bill_no}', title='{self.title[:20]}...')>"
    
    def get_process_history(self) -> list:
        """
        의안 처리 경과 정보 생성
        
        Returns:
            list: 처리 경과 정보 목록 [{"date": "날짜", "content": "내용"}, ...]
        """
        process_history = []
        
        # 제안일
        if self.proposal_date:
            process_history.append({
                "date": self.proposal_date.strftime("%Y-%m-%d"),
                "content": "발의"
            })
        
        # 표결일
        if self.vote_date:
            process_history.append({
                "date": self.vote_date.strftime("%Y-%m-%d"),
                "content": f"표결: {self.vote_result or '정보 없음'}"
            })
        
        # 처리 경과 정보 날짜순 정렬
        return sorted(process_history, key=lambda x: x["date"])

# Member 모델에 bills 관계 설정 (순환 참조 문제 해결)
Member.bills = relationship("Bill", order_by=Bill.proposal_date.desc(), back_populates="proposer_member")
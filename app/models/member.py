from sqlalchemy import Column, Integer, String, Date, Float, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base

class Member(Base):
    """
    국회의원 정보를 저장하는 모델
    
    기본 정보(이름, 정당, 선거구 등)와 통계 정보(발의안 수, 출석률 등)를 포함
    """
    __tablename__ = "members"

    # 기본 식별 필드
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False, comment="국회의원 이름")
    
    # 기본 인적사항
    hanja_name = Column(String, nullable=True, comment="한자명")
    eng_name = Column(String, nullable=True, comment="영문명")
    birth_date = Column(Date, nullable=True, comment="생년월일")
    birth_gbn = Column(String, nullable=True, comment="음/양력 구분")
    
    # 소속 정보
    position = Column(String, nullable=True, comment="직책명")
    party = Column(String, index=True, comment="정당명")
    district = Column(String, index=True, comment="선거구")
    
    # 위원회 관련 정보
    committee = Column(String, nullable=True, comment="대표 위원회")
    committees = Column(Text, nullable=True, comment="소속 위원회 목록 (쉼표로 구분)")
    
    # 선거 관련 정보
    reele_gbn = Column(String, nullable=True, comment="재선 구분")
    units = Column(String, nullable=True, comment="당선 수")
    
    # 연락처 정보
    tel_no = Column(String, nullable=True, comment="전화번호")
    email = Column(String, nullable=True, comment="이메일")
    homepage = Column(String, nullable=True, comment="홈페이지")
    
    # 통계 및 활동 점수 관련 필드
    num_bills = Column(Integer, default=0, comment="발의안 개수")
    attendance_rate = Column(Float, default=0.0, comment="참석율 (%)") 
    speech_count = Column(Integer, default=0, comment="발언 횟수")
    activity_score = Column(Float, default=0.0, comment="활동 점수 (자체 계산)")
    bill_pass_rate = Column(Float, default=0.0, comment="법안 통과율 (%)")
    
    # 데이터 관리용 필드
    is_active = Column(Boolean, default=True, comment="현직 여부")
    last_updated = Column(Date, nullable=True, comment="정보 최종 업데이트 일자")

    # relationship은 bill.py에서 정의 (순환 참조 방지)
    # bills = relationship("Bill", back_populates="proposer_member")
    
    def __repr__(self):
        """객체 문자열 표현"""
        return f"<Member(id={self.id}, name='{self.name}', party='{self.party}')>"
    
    def calculate_activity_score(self) -> float:
        """
        국회의원 활동 점수 계산
        
        가중치:
        - 발의안 수: 40%
        - 출석률: 30%
        - 발언 횟수: 20%
        - 법안통과율: 10%
        
        Returns:
            float: 0-100 사이의 활동 점수
        """
        # 각 항목별 정규화를 위한 최대값
        max_bills = 50
        max_speech_count = 200
        
        # 각 항목별 점수 계산 (0-100 범위)
        bills_score = min(100, (self.num_bills / max_bills) * 100)
        attendance_score = self.attendance_rate  # 이미 0-100 범위
        speech_score = min(100, (self.speech_count / max_speech_count) * 100)
        pass_rate_score = self.bill_pass_rate if self.bill_pass_rate else 0
        
        # 가중치 적용하여 최종 점수 계산
        activity_score = (
            bills_score * 0.4 +
            attendance_score * 0.3 +
            speech_score * 0.2 +
            pass_rate_score * 0.1
        )
        
        return round(activity_score, 1)
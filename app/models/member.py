from sqlalchemy import Column, Integer, String, Date, Float, Boolean, Text

from app.db.session import Base

class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    hanja_name = Column(String, nullable=True)  # 한자명
    eng_name = Column(String, nullable=True)    # 영문명
    birth_date = Column(Date, nullable=True)    # 생년월일
    birth_gbn = Column(String, nullable=True)   # 음/양력 구분
    position = Column(String, nullable=True)    # 직책명
    party = Column(String, index=True)          # 정당명
    district = Column(String, index=True)       # 선거구
    
    # 추가 필드
    committee = Column(String, nullable=True)   # 대표 위원회
    committees = Column(Text, nullable=True)    # 소속 위원회 목록 (쉼표로 구분)
    reele_gbn = Column(String, nullable=True)   # 재선 구분
    units = Column(String, nullable=True)       # 당선 수
    
    # 홈페이지, 이메일, 전화번호 등 추가
    tel_no = Column(String, nullable=True)      # 전화번호
    email = Column(String, nullable=True)       # 이메일
    homepage = Column(String, nullable=True)    # 홈페이지
    
    # 통계 및 활동 점수 관련 필드
    num_bills = Column(Integer, default=0)       # 발의안 개수
    attendance_rate = Column(Float, default=0.0) # 참석율 (%)
    speech_count = Column(Integer, default=0)    # 발언 횟수
    activity_score = Column(Float, default=0.0)  # 활동 점수 (자체 계산)
    bill_pass_rate = Column(Float, default=0.0)  # 법안 통과율 (%)
    
    # 데이터 관리용 필드
    is_active = Column(Boolean, default=True)
    last_updated = Column(Date, nullable=True)
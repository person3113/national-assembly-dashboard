import os
from dotenv import load_dotenv
from pathlib import Path

# .env 파일 로드
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

class Settings:
    # 애플리케이션 기본 설정
    PROJECT_NAME: str = "국회정보 대시보드"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = os.getenv("DEBUG", "False") == "True"
    
    # 국회정보 API 설정
    ASSEMBLY_API_KEY: str = os.getenv("ASSEMBLY_API_KEY")
    ASSEMBLY_API_BASE_URL: str = "https://open.assembly.go.kr/portal/openapi"
    
    # 데이터베이스 설정
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    
    # 기타 설정
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

settings = Settings()
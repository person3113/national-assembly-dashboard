# 2. 가상환경 생성 및 활성화
// powershell 말고 cmd에서 해야 함.
python -m venv venv // 이미 되어 있음.
venv\Scripts\activate

# FastAPI와 Uvicorn을 설치합니다. Uvicorn은 ASGI 서버로, FastAPI 애플리케이션을 실행하는 데 사용됩니다.
pip install fastapi uvicorn // 이미 되어 있음.

# 애플리케이션 실행:
uvicorn app.main:app --reload
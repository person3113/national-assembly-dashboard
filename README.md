# 실행방법

- powershell 말고 cmd에서 해야 함.
- 가상환경 생성 및 활성화
  - python -m venv venv // 이미 되어 있음.
  - venv\Scripts\activate
- FastAPI와 Uvicorn을 설치합니다.Uvicorn은 ASGI 서버로, FastAPI 애플리케이션을 실행하는 데 사용됩니다.
  - pip install fastapi uvicorn // 이미 되어 있음.
- 애플리케이션 실행
  - uvicorn app.main:app --reload
- 가상환경을 비활성화
  - deactivate


> - 우리 사이트 API 문서: http://127.0.0.1:8000/docs
> - api test 경로: http://127.0.0.1:8000/admin/test-api
> - api 데이터 동기화: http://127.0.0.1:8000/admin/sync-data

# 개발 과정

- [v] 국회의원 목록을 서버 시작할 때부터 api 호출하도록 수정.
- [v] 국회의원 상세 정보가 다 기본값으로 세팅되어 있는데, 실제 데이터를 반영하도록 수정하기.
  - 국회의원 인적사항 api에서 제공하는 정보는 다 반영됨.
  - 출석률이나 활동 점수나 그런 api에서 직접적으로 제공 안 되는 정보는 일단 미구현.
- [v] 국회의원 목록 검색에서 정당을 최신으로 업데이트. 하드 코딩으로. 일단.

---

- [] 의안 전체 목록이 나오도록 수정.

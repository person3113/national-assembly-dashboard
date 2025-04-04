# 실행방법

- 사전 준비
  - powershell 말고 cmd에서 해야 함.
  - 컴퓨터에 git과 python이 깔려 있어야 됨
  - 처음 클론했다면 .env 파일을 만들어야 함.
    - .gitignore에 .env 추가되어 있어서 개인적으로 만들어야 함.
    - .env 파일에 open api에서 발급받은 키를 넣어야 함.
- 가상환경 생성 및 활성화
  - python -m venv venv // 처음 clone했을 때만 입력
  - venv\Scripts\activate
- 필요한 라이브러리(패키지) 전부 다운
  - pip install -r requirements.txt // 처음 clone했을 때만 입력 or pull 받았을 때만 입력
- 설치 확인
  - pip list // 뭔가 오류가 나면 설치되었는지 확인
- 애플리케이션 실행
  - uvicorn app.main:app --reload
- 가상환경을 비활성화
  - deactivate


> - 우리 사이트 API 문서: http://127.0.0.1:8000/docs

# 개발 과정

정성오 개발 (25.3.21)
- [v] 국회의원 목록을 서버 시작할 때부터 api 호출하도록 수정.
- [v] 국회의원 상세 정보가 다 기본값으로 세팅되어 있는데, 실제 데이터를 반영하도록 수정하기.
  - 국회의원 인적사항 api에서 제공하는 정보는 다 반영됨.
  - 출석률이나 활동 점수나 그런 api에서 직접적으로 제공 안 되는 정보는 일단 미구현.
- [v] 국회의원 목록 검색에서 정당을 최신으로 업데이트. 하드 코딩으로. 일단.

---
정성오 개발 (25.3.23)
- [v] 의안 전체 목록이 나오도록 수정. => 일단 22대 의안만 끌고왔음.
  - 의안별 표결현황 -> 대수 넘기고 의안 id 다 끌고오기
  - 의안정보 통합 api -> 끌고 온 id 전부 이용해서 해당 대수 의안 정보 목록 싹 끌고 오기.
  - 의안 제안자정보 -> 끌고온 의안마다 각 제안자와 대표 제안자가 누구인지 파악하는 용도. 각 의원 별 활동점수에 대한 정보이니까. /members 화면에서도 각 의원 별 발의안 수도 표시해야 하니까.
- [v] 일단 22대 국회 발의안과 의원은 따로 내 앱 db 자체에 다 저장해놓고 api 호출 없이 쓰도록 함.
  - 주기적으로 예로 하루에 한 번, 아님 1주일에 한 번씩 다시 api 호출해서 새로 추가된 목록은 내 앱의 db에 추가하는 식으로 동작하는 건 어떨까.
  - 확인은 못했지만, 이단 scheduler 이용하긴 함.
- [v] /bills에서 페이지네이션, 즉 페이지 버튼이 현재 1, 2이런 식으로 하나만 화면에 나오거든. 예로 데이터 100개 있고 한 페이지에 50개 있으면, 1,2페이지 버튼이 나와야 하는데 1페이지 버튼만 나오는 상황. 이걸 수정.
- [v] footer를 항상 화면 제일 밑에 붙어있게 고정시키기
- [v] 의원 상세페이지에서 최근 발언 부분과 관련된 코드 빼기
- [v] 의원 상세페이지에서 최근 발의안 부분 눌렀을 때 제대로 안 됨. 확실한 경로로 의안 상세페이지로 이동할 수 있도록 수정

---

정성오 개발 (25.3.27)
- [v] 홈 화면과 활동 랭킹에서 더미 데이터가 아니라, 실제 국회의원 데이터를 가지고 표시하도록 수정하기

정성오 (25.3.28)
- [v] 기능 구현 대신, 리팩토링하고 다듬기
  - [v] 불필요한 apscheduler 코드 삭제하기. 어차피 서버 시작할 때 최신 정보 조회해보니까.
  - [v] dummy 데이터 관련 코드도 그냥 다 삭제하기. 더미 데이터가 아니라 실제 데이터를 사용하도록 수정했으니까.
  - [v] /admin 관련 코드 다 삭제해도 앱에 문제 없으면 싹 삭제하고 정리하기.
  - [v] 전체적으로 코드 다듬고 리팩토링하면서 주석도 달고 이해하기 쉽고 가독성 좋게 코드 리팩토링하기.
    - 불필요하게 중복되는 건 제거하고, 함수화하고, 클래스화하고, 변수명도 명확하게 수정하기.(물론 필요하면)
- [v] 리팩토링 후 발의안 페이지 번호 누를 때 오류 발생. 1,2,3번은 괜찮은데 그 이후 페이지네이션 번호 누르면 internal server error 발생.

# 개발 예정

- [] op.gg 느낌을 더 강하게 하기. ui나 그런 걸.
  - [] 추가로 롤 티어처럼 국회의원 랭킹순위 기준으로 상위 1%는 master 뭐 이런 식으로 하는 것도 좋을 듯.
- [] 발의안 페이지에서 검색 조건에 따라 internal server error가 발생하는 경우가 있음. 이 부분 수정하기.
  - 여러 조건 별로 테스트 해보면서 수정하기
  - 해보면서 발생하는 에러 로그 참고해서 수정하기기
- [] 국회의원 상세 페이지에서 발의한 게 없다면, 그냥 발의한 게 없다고 표시하도록 수정하기.
- [] 활동랭킹, 홈화면에 보이는 차트에서, 국민의 힘은 빨간색, 민주당은 파란색 등 당의 색깔 알맞게 수정하기

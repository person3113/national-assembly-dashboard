import requests
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.core.config import settings

class AssemblyAPI:
    def __init__(self):
        self.base_url = settings.ASSEMBLY_API_BASE_URL
        self.api_key = settings.ASSEMBLY_API_KEY
        
    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict:
        """국회정보 API에 요청을 보내는 기본 메서드"""
        # API 키 추가
        params["KEY"] = self.api_key
        # 응답 형식 JSON으로 설정
        params["Type"] = "json"
        
        url = f"{self.base_url}/{endpoint}"
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"API 요청 실패: {response.status_code}, {response.text}")
        
        return response.json()
    
    def get_members(self, 
                   assembly_term: int = 22,  # 22대 국회 기본값
                   name: Optional[str] = None,
                   party: Optional[str] = None) -> List[Dict]:
        """국회의원 인적사항 조회"""
        endpoint = "nzmimeepazxkubdpn"  # 국회의원 인적사항 API 엔드포인트
        
        params = {
            "ASSEMBLY": assembly_term,  # 대수
            "pIndex": 1,               # 페이지 번호
            "pSize": 300               # 한 페이지 결과 수 (최대값으로 설정)
        }
        
        # 필터링 옵션 추가
        if name:
            params["HG_NM"] = name     # 이름으로 검색
        if party:
            params["POLY_NM"] = party  # 정당으로 검색
            
        response_data = self._make_request(endpoint, params)
        
        # API 응답에서 국회의원 목록 추출
        try:
            # API 응답 구조에 맞게 데이터 추출 (실제 API 응답 구조에 따라 수정 필요)
            members_data = response_data["nzmimeepazxkubdpn"][1]["row"]
            return members_data
        except (KeyError, IndexError) as e:
            print(f"API 응답 파싱 오류: {e}")
            return []
            
    def get_bill_vote_results(self, 
                             assembly_term: int = 22,
                             bill_id: Optional[str] = None) -> List[Dict]:
        """의안별 표결 현황 조회"""
        endpoint = "nzmimeepazyrjsxdq"  # 의안별 표결현황 API 엔드포인트
        
        params = {
            "ASSEMBLY": assembly_term,  # 대수
            "pIndex": 1,                # 페이지 번호
            "pSize": 100                # 한 페이지 결과 수
        }
        
        # 특정 의안 번호가 제공된 경우 추가
        if bill_id:
            params["BILL_ID"] = bill_id
            
        response_data = self._make_request(endpoint, params)
        
        # API 응답에서 표결 현황 추출
        try:
            vote_results = response_data["nzmimeepazyrjsxdq"][1]["row"]
            return vote_results
        except (KeyError, IndexError) as e:
            print(f"API 응답 파싱 오류: {e}")
            return []
    
    def get_member_vote_results(self, 
                               assembly_term: int = 22,
                               member_name: Optional[str] = None,
                               bill_id: Optional[str] = None) -> List[Dict]:
        """국회의원 표결정보 조회"""
        endpoint = "nzmimeepazxkubdpq"  # 국회의원 본회의 표결정보 API 엔드포인트
        
        params = {
            "ASSEMBLY": assembly_term,  # 대수
            "pIndex": 1,                # 페이지 번호
            "pSize": 100                # 한 페이지 결과 수
        }
        
        # 필터링 옵션 추가
        if member_name:
            params["HG_NM"] = member_name  # 이름으로 검색
        if bill_id:
            params["BILL_ID"] = bill_id    # 의안 번호로 검색
            
        response_data = self._make_request(endpoint, params)
        
        # API 응답에서 표결정보 추출
        try:
            vote_data = response_data["nzmimeepazxkubdpq"][1]["row"]
            return vote_data
        except (KeyError, IndexError) as e:
            print(f"API 응답 파싱 오류: {e}")
            return []
    
    def get_committee_info(self, 
                          assembly_term: int = 22,
                          committee_name: Optional[str] = None) -> List[Dict]:
        """위원회 현황 정보 조회"""
        endpoint = "nzmimeepazxkubdpc"  # 위원회 현황 정보 API 엔드포인트
        
        params = {
            "ASSEMBLY": assembly_term,  # 대수
            "pIndex": 1,                # 페이지 번호
            "pSize": 50                 # 한 페이지 결과 수
        }
        
        # 특정 위원회 이름이 제공된 경우 추가
        if committee_name:
            params["CURR_COMMITTEE"] = committee_name
            
        response_data = self._make_request(endpoint, params)
        
        # API 응답에서 위원회 정보 추출
        try:
            committee_data = response_data["nzmimeepazxkubdpc"][1]["row"]
            return committee_data
        except (KeyError, IndexError) as e:
            print(f"API 응답 파싱 오류: {e}")
            return []
    
    def get_speech_records(self, 
                          assembly_term: int = 22,
                          member_name: Optional[str] = None,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> List[Dict]:
        """국회의원 영상회의록(발언영상) 조회"""
        endpoint = "nzmimeepazxkubdph"  # 국회의원 영상회의록 API 엔드포인트
        
        # 날짜 기본값 설정 (없을 경우)
        if not start_date:
            start_date = "20240101"  # 2024년 1월 1일부터
        if not end_date:
            today = datetime.now().strftime("%Y%m%d")
            end_date = today  # 오늘까지
        
        params = {
            "ASSEMBLY": assembly_term,  # 대수
            "SD": start_date,           # 시작일
            "ED": end_date,             # 종료일
            "pIndex": 1,                # 페이지 번호
            "pSize": 100                # 한 페이지 결과 수
        }
        
        # 특정 의원 이름이 제공된 경우 추가
        if member_name:
            params["SPKR_NM"] = member_name
            
        response_data = self._make_request(endpoint, params)
        
        # API 응답에서 발언영상 정보 추출
        try:
            speech_data = response_data["nzmimeepazxkubdph"][1]["row"]
            return speech_data
        except (KeyError, IndexError) as e:
            print(f"API 응답 파싱 오류: {e}")
            return []

# 서비스 인스턴스 생성
assembly_api = AssemblyAPI()
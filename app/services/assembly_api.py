import logging
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

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
        
        # API URL 형식 확인 (가이드 문서 참고)
        url = f"{self.base_url}/{endpoint}"
        
        # 요청 전 로깅 (디버깅용)
        logger.info(f"API 요청: {url}, 파라미터: {params}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            
            # 디버깅을 위한 응답 로깅
            logger.info(f"API 응답 상태 코드: {response.status_code}")
            
            # HTTP 오류 확인
            if response.status_code != 200:
                logger.error(f"HTTP 오류: {response.status_code}, 응답: {response.text}")
                raise Exception(f"API 요청 실패: {response.status_code}, {response.text}")
            
            # JSON 응답 확인
            result = response.json()
            
            # 응답 디버깅 
            if "RESULT" in result and result["RESULT"]["CODE"] != "INFO-000":
                error_code = result["RESULT"]["CODE"]
                error_msg = result["RESULT"]["MESSAGE"]
                
                # 데이터 없음 코드는 오류로 처리하지 않고 빈 결과로 처리
                if error_code == "INFO-200" and "해당하는 데이터가 없습니다" in error_msg:
                    logger.info(f"API 응답: {error_code}, {error_msg} - 데이터 없음으로 처리")
                    # 데이터가 없는 경우 빈 결과 구조 반환
                    if endpoint == "ALLBILL":
                        return {"ALLBILL": {"row": []}}
                    else:
                        return {endpoint: [{"header": {}}, {"row": []}]}
                else:
                    # 기타 오류는 로깅하고 예외 발생
                    logger.error(f"API 오류 응답: {error_code}, {error_msg}")
                    raise Exception(f"API 오류: {error_code}, {error_msg}")
                    
            return result
            
        except requests.exceptions.RequestException as e:
            # 요청 관련 오류
            logger.error(f"API 요청 중 오류: {str(e)}")
            raise Exception(f"API 요청 오류: {str(e)}")
            
        except ValueError as e:
            # JSON 파싱 오류
            logger.error(f"API 응답 JSON 파싱 오류: {str(e)}")
            raise Exception(f"API 응답 파싱 오류: {str(e)}")
            
        except Exception as e:
            # 기타 오류
            logger.error(f"API 요청 중 예상치 못한 오류: {str(e)}")
            raise
    
    def get_members(self, 
                assembly_term: int = 22,  # 22대 국회 기본값
                name: Optional[str] = None,
                party: Optional[str] = None) -> List[Dict]:
        """국회의원 인적사항 조회"""
        endpoint = "nwvrqwxyaytdsfvhu"  # 국회의원 인적사항 API 엔드포인트
        
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
            
        try:
            response_data = self._make_request(endpoint, params)
            
            # API 응답에서 국회의원 목록 추출
            try:
                # 실제 API 응답 구조 확인
                if endpoint in response_data and len(response_data[endpoint]) > 1:
                    members_data = response_data[endpoint][1]["row"]
                    
                    # 디버깅: 첫 번째 의원 데이터의 모든 필드 출력
                    if len(members_data) > 0:
                        first_member = members_data[0]
                        logger.info(f"첫 번째 의원 데이터 필드: {list(first_member.keys())}")
                        logger.info(f"첫 번째 의원 생년월일 관련 필드:")
                        for key in first_member.keys():
                            if "DATE" in key or "BTH" in key or "birth" in key.lower():
                                logger.info(f"  {key}: {first_member[key]}")
                    
                    return members_data
                else:
                    # 응답 구조가 다른 경우 전체 응답 로깅
                    logger.error(f"API 응답 구조 예상과 다름: {response_data}")
                    return []
            except (KeyError, IndexError) as e:
                logger.error(f"API 응답 파싱 오류: {e}, 응답: {response_data}")
                return []
        except Exception as e:
            logger.error(f"국회의원 정보 조회 중 오류: {str(e)}")
            return []

    def get_bills(self, 
             assembly_term: int = 22,
             bill_name: Optional[str] = None,
             proposer: Optional[str] = None,
             committee: Optional[str] = None,
             start_date: Optional[str] = None,
             end_date: Optional[str] = None,
             bill_id: Optional[str] = None,
             bill_no: Optional[str] = None,
             page_index: int = 1,
             page_size: int = 20) -> List[Dict]:
        """국회 의안정보 조회"""
        # 의안정보 조회 API 엔드포인트 (명세서 참조)
        endpoint = "ALLBILL"  # 의안정보 통합 API 엔드포인트
        
        # 파라미터 초기화
        params = {
            "pIndex": page_index,       # 페이지 위치 (필수)
            "pSize": page_size          # 페이지 당 요청 숫자 (필수)
        }
        
        # 제안자 처리 - PPSR_KND가 아닌 PPSR_NM 사용 (API 명세서 확인 필요)
        if proposer:
            params["PPSR_NM"] = proposer  # 제안자명 

        # bill_no 사용여부 결정
        if bill_name:
            params["BILL_NM"] = bill_name  # 의안명(선택)
        elif bill_no:
            params["BILL_NO"] = bill_no  # 의안번호
        else:
            # 의안번호 없이 검색하려면 다른 조건 필요
            # 모든 의안을 불러오고 싶은 경우 특정 기간 지정
            if not start_date:
                # 기본 기간 설정 (예: 22대 국회 개원일부터 현재까지)
                start_date = "20240530"  # 22대 국회 개원일
            params["AGE"] = assembly_term  # 국회대수 추가
        
        # 나머지 선택적 파라미터 추가
        if bill_id:
            params["BILL_ID"] = bill_id    # 의안ID(선택)
        if start_date:
            params["PROPOSE_FROM"] = start_date # 제안일(시작)
        if end_date:
            params["PROPOSE_TO"] = end_date     # 제안일(종료)
        if committee:
            params["COMMITTEE"] = committee     # 소관위원회명(선택)
            
        try:
            response_data = self._make_request(endpoint, params)
            
            # API 응답에서 의안 목록 추출
            try:
                # 로그로 응답 구조 확인 (디버깅용)
                logger.info(f"API 응답 구조: {response_data.keys()}")
                
                # 응답 구조 확인하고 적절하게 처리
                if "ALLBILL" in response_data and isinstance(response_data["ALLBILL"], dict) and "row" in response_data["ALLBILL"]:
                    bills_data = response_data["ALLBILL"]["row"]
                    return bills_data
                elif "ALLBILL" in response_data and isinstance(response_data["ALLBILL"], list) and len(response_data["ALLBILL"]) > 0:
                    # 리스트 형태로 반환된 경우 (인덱스 접근 방식 수정)
                    for item in response_data["ALLBILL"]:
                        if isinstance(item, dict) and "row" in item:
                            return item["row"]
                    
                    logger.error(f"응답에서 'row' 키를 찾을 수 없음: {response_data}")
                    return []
                else:
                    # "해당하는 데이터가 없습니다." 메시지 처리
                    if "RESULT" in response_data and response_data["RESULT"]["CODE"] == "INFO-200":
                        logger.info(f"발의안 검색 결과 없음: {params}")
                        return []
                        
                    logger.error(f"API 응답 구조 예상과 다름: {response_data}")
                    return []
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"API 응답 파싱 오류: {e}, 응답: {response_data}")
                return []
        except Exception as e:
            logger.error(f"의안 정보 조회 중 오류: {str(e)}")
            return []

    def get_bill_detail(self, bill_id: str = None, bill_no: str = None) -> Dict:
        """의안 상세정보 조회"""
        # 의안상세정보 조회 API 엔드포인트
        endpoint = "ALLBILL"  # 동일한 엔드포인트 사용
        
        # BILL_NO(의안번호)는 필수 파라미터
        if not bill_no:
            logger.error("의안번호(BILL_NO)가 필요합니다.")
            return {}
        
        params = {
            "pIndex": 1,    # 페이지 위치 (필수)
            "pSize": 1,     # 페이지 당 요청 숫자 (필수)
            "BILL_NO": bill_no  # 의안번호 (필수)
        }
        
        # 의안ID는 선택적 파라미터
        if bill_id:
            params["BILL_ID"] = bill_id
        
        try:
            response_data = self._make_request(endpoint, params)
            
            # API 응답에서 의안 상세정보 추출
            try:
                # 로그로 응답 구조 확인 (디버깅용)
                logger.info(f"API 응답 구조: {response_data.keys()}")
                
                # 응답 구조 확인하고 적절하게 처리
                if "ALLBILL" in response_data and isinstance(response_data["ALLBILL"], dict) and "row" in response_data["ALLBILL"]:
                    bills_data = response_data["ALLBILL"]["row"]
                    # 첫 번째 결과만 반환 (상세정보이므로 단일 항목이어야 함)
                    return bills_data[0] if bills_data else {}
                elif "ALLBILL" in response_data and isinstance(response_data["ALLBILL"], list) and len(response_data["ALLBILL"]) > 0:
                    # 리스트 형태로 반환된 경우 (인덱스 접근 방식 수정)
                    for item in response_data["ALLBILL"]:
                        if isinstance(item, dict) and "row" in item:
                            return item["row"][0] if item["row"] else {}
                    
                    logger.error(f"응답에서 'row' 키를 찾을 수 없음: {response_data}")
                    return {}
                else:
                    logger.error(f"API 응답 구조 예상과 다름: {response_data}")
                    return {}
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"API 응답 파싱 오류: {e}, 응답: {response_data}")
                return {}
        except Exception as e:
            logger.error(f"의안 상세정보 조회 중 오류: {str(e)}")
            return {}

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
        # API 엔드포인트 확인 필요
        endpoint = "npeslxqbanwkimebr"  # 국회의원 영상회의록 API 엔드포인트 수정
        
        # 날짜 기본값 설정 (없을 경우)
        if not start_date:
            start_date = "20240101"  # 2024년 1월 1일부터
        if not end_date:
            today = datetime.now().strftime("%Y%m%d")
            end_date = today  # 오늘까지
        
        params = {
            "CT1": str(assembly_term),  # 대수 (필수)
            "TAKING_DATE": start_date,  # 회의일자 (필수)
            "pIndex": 1,                # 페이지 번호
            "pSize": 100                # 한 페이지 결과 수
        }
        
        # 특정 의원 이름이 제공된 경우 추가
        if member_name:
            params["ESSENTIAL_PERSON"] = member_name  # 발언자
                
        try:
            response_data = self._make_request(endpoint, params)
            
            # API 응답에서 발언영상 정보 추출
            try:
                # API 응답 구조 확인 필요
                if endpoint in response_data and len(response_data[endpoint]) > 1:
                    speech_data = response_data[endpoint][1]["row"]
                    return speech_data
                else:
                    logger.warning(f"API 응답에서 발언 데이터를 찾을 수 없음: {response_data}")
                    return []
            except (KeyError, IndexError) as e:
                logger.error(f"API 응답 파싱 오류: {e}")
                return []
        except Exception as e:
            logger.error(f"발언 정보 조회 중 오류: {str(e)}")
            return []

# 서비스 인스턴스 생성
assembly_api = AssemblyAPI()
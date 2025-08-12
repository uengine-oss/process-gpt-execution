"""
FCM Service HTTP Client

FCM 서비스와 통신하기 위한 클라이언트 함수들
"""
import os
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# FCM 서비스 URL 설정
FCM_SERVICE_URL = os.getenv("FCM_SERVICE_URL", "http://fcm-service:8666")

def send_fcm_notification(user_id: str, notification_data: dict) -> dict:
    """
    FCM 서비스를 통해 푸시 알림을 전송합니다.
    
    Args:
        user_id (str): 사용자 ID (이메일)
        notification_data (dict): 알림 데이터
    
    Returns:
        dict: 전송 결과
    """
    try:
        url = f"{FCM_SERVICE_URL}/send-notification"
        
        payload = {
            "user_id": user_id,
            "title": notification_data.get('title', '알림'),
            "body": notification_data.get('body', notification_data.get('description', '')),
            "type": notification_data.get('type', 'general'),
            "url": notification_data.get('url', ''),
            "from_user_id": notification_data.get('from_user_id', ''),
            "data": notification_data.get('data', {})
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"FCM 서비스 오류: {response.status_code} - {response.text}")
            return {"success": False, "message": f"HTTP {response.status_code}: {response.text}"}
            
    except requests.exceptions.RequestException as e:
        logger.error(f"FCM 서비스 통신 오류: {e}")
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"FCM 클라이언트 오류: {e}")
        return {"success": False, "message": str(e)}

def get_device_token(user_id: str) -> Optional[str]:
    """
    FCM 서비스를 통해 사용자의 디바이스 토큰을 조회합니다.
    
    Args:
        user_id (str): 사용자 ID (이메일)
    
    Returns:
        Optional[str]: 디바이스 토큰
    """
    try:
        url = f"{FCM_SERVICE_URL}/device-token/{user_id}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('device_token')
        else:
            logger.error(f"FCM 서비스 오류: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"FCM 서비스 통신 오류: {e}")
        return None
    except Exception as e:
        logger.error(f"FCM 클라이언트 오류: {e}")
        return None

def check_fcm_service_health() -> bool:
    """
    FCM 서비스의 상태를 확인합니다.
    
    Returns:
        bool: 서비스 정상 여부
    """
    try:
        url = f"{FCM_SERVICE_URL}/health"
        
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('status') == 'healthy'
        else:
            return False
            
    except Exception as e:
        logger.error(f"FCM 서비스 헬스체크 오류: {e}")
        return False

# 기존 함수와의 호환성을 위한 래퍼 함수들
def send_fcm_message(user_id: str, notification_data: dict) -> dict:
    """기존 send_fcm_message 함수와의 호환성을 위한 래퍼"""
    return send_fcm_notification(user_id, notification_data)

def fetch_device_token(user_id: str) -> Optional[str]:
    """기존 fetch_device_token 함수와의 호환성을 위한 래퍼"""
    return get_device_token(user_id)
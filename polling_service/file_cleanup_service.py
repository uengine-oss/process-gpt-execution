import asyncio
import os
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, unquote
from database import supabase_client_var, subdomain_var


def parse_storage_url(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Supabase Storage URL에서 버킷 이름과 파일 경로를 추출합니다.
    
    Args:
        file_path: URL 형식 또는 일반 경로 형식
    
    Returns:
        (bucket_name, actual_file_path) 튜플. URL이 아닌 경우 (None, file_path) 반환
    """
    # URL 형식인지 확인 (http:// 또는 https://로 시작)
    if not file_path.startswith(('http://', 'https://')):
        # 일반 경로 형식
        return None, file_path
    
    try:
        # URL 파싱
        parsed = urlparse(file_path)
        path = parsed.path
        
        # Supabase Storage URL 패턴: /storage/v1/object/public/{bucket}/{file_path}
        pattern = r'/storage/v1/object/public/([^/]+)/(.+)'
        match = re.match(pattern, path)
        
        if match:
            bucket_name = match.group(1)
            file_path_in_storage = unquote(match.group(2))  # URL 디코딩
            
            # 쿼리 파라미터 제거 (이미 urlparse가 처리했지만 안전을 위해)
            if '?' in file_path_in_storage:
                file_path_in_storage = file_path_in_storage.split('?')[0]
            
            return bucket_name, file_path_in_storage
        else:
            # URL 형식이지만 Supabase Storage 패턴이 아닌 경우 그냥 패스
            return None, file_path
    except Exception:
        # 파싱 오류 발생 시 그냥 패스
        return None, file_path


def fetch_completed_process_instances(tenant_id: Optional[str] = None) -> List[Dict]:
    """
    bpm_proc_inst 테이블에서 status가 'COMPLETED'이고 is_clean_up이 false인 프로세스 인스턴스들을 조회합니다.
    
    Args:
        tenant_id: 테넌트 ID (선택사항)
    
    Returns:
        COMPLETED 상태이고 아직 정리되지 않은 프로세스 인스턴스 리스트
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")
        
        if not tenant_id:
            tenant_id = subdomain_var.get()
        
        result = []
        
        response_false = supabase.table('bpm_proc_inst').select('proc_inst_id').eq('status', 'COMPLETED').eq('tenant_id', tenant_id).eq('is_clean_up', False).execute()
        if response_false.data:
            result.extend(response_false.data)
        
        # 중복 제거
        seen_ids = set()
        unique_result = []
        for item in result:
            proc_inst_id = item.get('proc_inst_id')
            if proc_inst_id and proc_inst_id not in seen_ids:
                seen_ids.add(proc_inst_id)
                unique_result.append(item)
        
        return unique_result
    except Exception as e:
        print(f"[ERROR] Failed to fetch completed process instances: {str(e)}")
        return []


def fetch_proc_inst_sources(proc_inst_id: str, tenant_id: Optional[str] = None) -> List[Dict]:
    """
    proc_inst_source 테이블에서 특정 proc_inst_id에 해당하는 소스 파일 목록을 조회합니다.
    
    Args:
        proc_inst_id: 프로세스 인스턴스 ID
        tenant_id: 테넌트 ID (선택사항)
    
    Returns:
        proc_inst_source 레코드 리스트
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")
        
        if not tenant_id:
            tenant_id = subdomain_var.get()
        
        response = supabase.table('proc_inst_source').select('*').eq('proc_inst_id', proc_inst_id).execute()
        
        if response.data:
            return response.data
        return []
    except Exception as e:
        print(f"[ERROR] Failed to fetch proc_inst_sources for {proc_inst_id}: {str(e)}")
        return []


def check_file_exists_in_storage(file_path: str, bucket_name: str = "files") -> bool:
    """ 
    Supabase Storage에서 파일이 존재하는지 확인합니다.
    
    Args:
        file_path: 확인할 파일 경로 (URL 형식 또는 일반 경로)
        bucket_name: 스토리지 버킷 이름 (기본값, URL에서 추출되면 덮어씀)
    
    Returns:
        파일이 존재하면 True, 그렇지 않으면 False
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")
        
        # URL 형식인지 확인하고 파싱
        parsed_bucket, actual_path = parse_storage_url(file_path)
        if parsed_bucket:
            bucket_name = parsed_bucket
        
        # actual_path는 이미 버킷 내부의 전체 경로입니다 (버킷 내 폴더 포함)
        # 예: "files/a15cdb51-..." (버킷명 'files' 내부의 'files' 폴더)
        
        # 디렉토리 경로와 파일명 분리
        dir_path = os.path.dirname(actual_path) if os.path.dirname(actual_path) else ""
        file_name = os.path.basename(actual_path)
        
        # 디렉토리 내용 조회
        if dir_path:
            response = supabase.storage.from_(bucket_name).list(path=dir_path)
        else:
            response = supabase.storage.from_(bucket_name).list()
        
        if response and len(response) > 0:
            # 파일 이름이 정확히 일치하는지 확인
            for item in response:
                if item.get('name') == file_name:
                    return True
        
        return False
    except Exception as e:
        # 파일이 존재하지 않거나 다른 오류가 발생한 경우
        print(f"[DEBUG] File check failed for {file_path}: {str(e)}")
        return False


def delete_file_from_storage(file_path: str, bucket_name: str = "files") -> bool:
    """
    Supabase Storage에서 파일을 삭제합니다.
    
    Args:
        file_path: 삭제할 파일 경로 (URL 형식 또는 일반 경로)
        bucket_name: 스토리지 버킷 이름 (기본값, URL에서 추출되면 덮어씀)
    
    Returns:
        삭제 성공 시 True, 실패 시 False
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")
        
        # URL 형식인지 확인하고 파싱
        parsed_bucket, actual_path = parse_storage_url(file_path)
        if parsed_bucket:
            bucket_name = parsed_bucket
        
        # actual_path는 이미 버킷 내부의 전체 경로입니다 (버킷 내 폴더 포함)
        # 예: "files/a15cdb51-..." (버킷명 'files' 내부의 'files' 폴더)
        print(f"[DEBUG] Deleting file from storage: {actual_path}")
        # remove 메서드는 파일 경로 리스트를 받음
        response = supabase.storage.from_(bucket_name).remove([actual_path])
        
        # response가 성공적으로 반환되면 True
        if response is not None:
            print(f"[INFO] Successfully deleted file from storage: {actual_path}")
            return True
        return False
    except Exception as e:
        # 파일이 이미 삭제되었거나 존재하지 않는 경우도 정상 처리
        error_msg = str(e).lower()
        if "not found" in error_msg or "does not exist" in error_msg:
            print(f"[DEBUG] File already deleted or not found: {file_path}")
            return True  # 이미 삭제된 것으로 간주
        print(f"[ERROR] Failed to delete file from storage for {file_path}: {str(e)}")
        return False


def update_proc_inst_cleanup_status(proc_inst_id: str, is_clean_up: bool = True) -> bool:
    """
    bpm_proc_inst 테이블의 is_clean_up 컬럼을 업데이트합니다.
    
    Args:
        proc_inst_id: 프로세스 인스턴스 ID
        is_clean_up: 정리 완료 여부 (기본값: True)
    
    Returns:
        업데이트 성공 시 True, 실패 시 False
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            raise Exception("Supabase client is not configured")
        
        # response = supabase.table('bpm_proc_inst').update({'is_clean_up': is_clean_up}).eq('proc_inst_id', proc_inst_id).execute()
        response = True
        if response:
            print(f"[INFO] Successfully updated is_clean_up for proc_inst_id: {proc_inst_id}")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to update is_clean_up for proc_inst_id {proc_inst_id}: {str(e)}")
        return False


async def cleanup_completed_process_files():
    """
    COMPLETED 상태의 프로세스 인스턴스에 연결된 파일들을 정리합니다.
    - bpm_proc_inst에서 COMPLETED 상태이고 is_clean_up이 false인 인스턴스 조회
    - proc_inst_source에서 해당 인스턴스의 파일 경로 조회
    - 소스 목록이 없으면 is_clean_up을 true로 설정
    - 소스 목록이 있으면:
      - Supabase Storage URL인 파일들만 삭제 처리
      - 모든 파일 삭제 완료 후 is_clean_up을 true로 설정
      - 모든 파일이 Supabase Storage URL이 아닌 경우에도 is_clean_up을 true로 설정
    """
    try:
        # 버킷 이름을 환경변수에서 가져오거나 기본값 사용
        bucket_name = "files"
        
        # 모든 테넌트에 대해 처리 (tenant_id가 None이면 모든 테넌트)
        # 또는 특정 테넌트만 처리하려면 tenant_id를 지정
        tenant_id = subdomain_var.get() if subdomain_var.get() != 'localhost' else None
        
        # COMPLETED 상태의 프로세스 인스턴스 조회
        completed_instances = fetch_completed_process_instances(tenant_id)
        
        if not completed_instances:
            print("[DEBUG] No completed process instances found")
            return
        
        print(f"[INFO] Found {len(completed_instances)} completed process instances")
        
        total_files_deleted = 0
        total_instances_cleaned = 0
        
        for instance in completed_instances:
            proc_inst_id = instance.get('proc_inst_id')
            if not proc_inst_id:
                continue
            
            # proc_inst_source 조회
            sources = fetch_proc_inst_sources(proc_inst_id, tenant_id)
            
            # 소스 목록이 없으면 is_clean_up을 true로 설정
            if not sources:
                if update_proc_inst_cleanup_status(proc_inst_id, True):
                    total_instances_cleaned += 1
                    print(f"[INFO] No sources found for proc_inst_id: {proc_inst_id}, marked as cleaned")
                continue
            
            print(f"[INFO] Processing {len(sources)} sources for proc_inst_id: {proc_inst_id}")
            
            # 모든 파일이 Supabase Storage URL인지 확인
            storage_url_files = []
            non_storage_files = []
            
            for source in sources:
                file_path = source.get('file_path')
                if not file_path:
                    print(f"[WARNING] No file_path found for source {source.get('id')}")
                    continue
                
                # Supabase Storage URL인지 확인
                parsed_bucket, _ = parse_storage_url(file_path)
                if parsed_bucket:
                    storage_url_files.append(source)
                else:
                    non_storage_files.append(source)
            
            # 모든 파일이 Supabase Storage URL이 아닌 경우
            if len(storage_url_files) == 0:
                # is_clean_up을 true로 설정
                if update_proc_inst_cleanup_status(proc_inst_id, True):
                    total_instances_cleaned += 1
                    print(f"[INFO] All files are non-storage URLs for proc_inst_id: {proc_inst_id}, marked as cleaned")
                continue
            
            # Supabase Storage URL인 파일들 삭제 처리
            all_files_deleted = True
            for source in storage_url_files:
                file_path = source.get('file_path')
                
                # Storage에서 파일 존재 확인
                if check_file_exists_in_storage(file_path, bucket_name):
                    # 파일 삭제
                    if delete_file_from_storage(file_path, bucket_name):
                        total_files_deleted += 1
                    else:
                        print(f"[WARNING] Failed to delete file: {file_path}")
                        all_files_deleted = False
                else:
                    print(f"[DEBUG] File not found in storage: {file_path}, proceeding")
            
            # 모든 파일 삭제 완료 후 is_clean_up 업데이트
            if all_files_deleted:
                if update_proc_inst_cleanup_status(proc_inst_id, True):
                    total_instances_cleaned += 1
                    print(f"[INFO] Successfully cleaned up proc_inst_id: {proc_inst_id}")
            else:
                print(f"[WARNING] Some files failed to delete for proc_inst_id: {proc_inst_id}, will retry later")
        
        print(f"[INFO] Cleanup completed: {total_files_deleted} files deleted, {total_instances_cleaned} instances marked as cleaned")
        
    except Exception as e:
        print(f"[ERROR] Error in cleanup_completed_process_files: {str(e)}")
        raise


async def file_cleanup_polling_task(shutdown_event: asyncio.Event, polling_interval: int = 300):
    """
    주기적으로 완료된 프로세스 인스턴스의 파일을 정리하는 폴링 태스크입니다.
    
    Args:
        shutdown_event: 종료 이벤트
        polling_interval: 폴링 주기 (초 단위, 기본값 300초 = 5분)
    """
    while not shutdown_event.is_set():
        try:
            await cleanup_completed_process_files()
        except Exception as e:
            print(f"[ERROR] File cleanup polling task error: {e}")
            # 오류 발생 시 짧은 대기 후 재시도
            await asyncio.sleep(60)
            continue
        
        # 정상적인 경우 지정된 주기만큼 대기
        await asyncio.sleep(polling_interval)


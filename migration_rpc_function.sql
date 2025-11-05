DROP TABLE IF EXISTS proc_def_backup;
CREATE TABLE proc_def_backup (
    uuid uuid NOT NULL DEFAULT gen_random_uuid (),
    id TEXT NULL,
    name TEXT NULL,
    definition JSONB NULL,
    bpmn TEXT NULL,
    tenant_id TEXT NULL,
    isdeleted BOOLEAN DEFAULT FALSE,
);

-- 마이그레이션 대상 프로세스 조회를 위한 RPC 함수
-- lock 테이블에 id가 없거나 user_id가 특정 값인 경우만 반환
DROP FUNCTION IF EXISTS get_migration_target_processes;


CREATE OR REPLACE FUNCTION get_migration_target_processes(
    batch_size INTEGER DEFAULT 5,
    cursor_after_id TEXT DEFAULT NULL,
    target_tenant_id TEXT DEFAULT NULL,
    lock_user_id TEXT DEFAULT NULL
)
RETURNS TABLE (
    id TEXT,
    name TEXT,
    definition JSONB,
    bpmn TEXT
) 
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        pd.id,
        pd.name,
        pd.definition,
        pd.bpmn
    FROM proc_def pd
    LEFT JOIN lock l ON l.id = pd.id AND l.tenant_id = pd.tenant_id
    WHERE 
        pd.isdeleted = false
        AND pd.definition IS NOT NULL
        AND pd.bpmn IS NOT NULL
        AND pd.bpmn LIKE '%"inputMapping"%'
        AND (
            -- lock이 없는 경우
            l.id IS NULL
            OR 
            -- lock이 있지만 user_id가 허용된 값인 경우
            l.user_id = lock_user_id
        )
        AND (
            target_tenant_id IS NULL 
            OR pd.tenant_id = target_tenant_id
        )
        AND (
            cursor_after_id IS NULL 
            OR pd.id > cursor_after_id
        )
    ORDER BY pd.id
    LIMIT batch_size;
END;
$$;

-- 함수 실행 권한 부여 (필요한 경우)
-- GRANT EXECUTE ON FUNCTION get_migration_target_processes TO your_role_name;

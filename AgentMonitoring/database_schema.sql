CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    todo_id TEXT,          -- todolist 항목 ID
    proc_inst_id TEXT,     -- 프로세스 인스턴스 ID
    event_type TEXT NOT NULL,    -- 🆕 type → event_type
    crew_type TEXT,              -- 🆕 새로 추가!
    data JSONB NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS todolist (
    id TEXT PRIMARY KEY,
    activity_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool TEXT,
    status TEXT DEFAULT 'PENDING',
    draft JSONB,
    consumer TEXT,
    proc_inst_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE events DISABLE ROW LEVEL SECURITY;
ALTER TABLE todolist DISABLE ROW LEVEL SECURITY;
# process-gpt-execution

## Install Dev Env
```
pipenv install
pipenv shell
set OPENAI_API_KEY=<OPENAI_API_KEY>
set SUPABASE_SECRET_KEY_DEV=<JWT_SECRET_KEY>
set SUPABASE_URL_DEV=<SUPABASE_URL>
set SUPABASE_KEY_DEV=<SERVICE_ROLE_KEY>
python main.py

```

# API Test

```
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="company_entrance" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="$INST_ID" input[activity_id]="congrate" # 400  error
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="invalid instance id" input[activity_id]="registration"  # 404 error
http :8000/complete/invoke input[answer]="지원분야는 SW engineer" input[process_instance_id]="$INST_ID" input[activity_id]="registration"  | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['nextActivities'])" 
# next activity id should be 'nextMail'
http :8000/complete/invoke input[answer]="no comment" input[process_instance_id]="$INST_ID" input[activity_id]="nextMail"


# 입사지원2: 입사 지원서 이미지 파일을 기반으로한: 
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="company_entrance" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID

http :8000/vision-complete/invoke input[answer]="세부 지원사항은 지원서에 확인해주십시오" input[process_instance_id]="$INST_ID" input[activity_id]="registration" 


# vacation use process
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="vacation_request" input[answer]="The total number of vacation days requested is 5, starting from February 5, 2024, to February 10, 2024, for the reason of travel" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="승인합니다" input[process_instance_id]="$INST_ID" input[activity_id]="manager_approval" # 400  error

# vacation addition process
INST_ID=$(http :8000/complete/invoke input[process_instance_id]="new" input[process_definition_id]="vacation_addition" input[answer]="5일간 휴가를 추가합니다" | python3 -c "import sys, json; print(json.loads(json.loads(sys.stdin.read())['output'])['instanceId'])")
echo $INST_ID
http :8000/complete/invoke input[answer]="승인합니다" input[process_instance_id]="$INST_ID" input[activity_id]="manager_approval" # 400  error
```



## Setting VSCode Debug Env
- Press Cmd+P to open search box and Enter ">" to select ">Python Interpreter" and set the right environment.
- Open main.py and Set breakpoints on main.py at some line to stop the execution:

```
def combine_input_with_process_definition(input):
    # 프로세스 인스턴스를 DB에서 검색
    
    process_instance_id = input.get('process_instance_id')  # 'process_instance_id' 키에 대한 접근 추가
>>    activity_id = input.get('activity_id')  <<< DEBUG POINT

```

- Switch to the Debug perspective 
- Press the Run button with the option "Python: Current File" (don't forget to leave the main.py file opened and the editor tab selected)

- You may face some dependency error or OPENAI_API_KEY related error. When it comes to you, do these:
```
# firstly Ctrl+C to stop the current debug session inside the terminal the debugger runs
# insert these commands:
pipenv shell
export OPENAI_API_KEY=sk-...
# Try to run the debugger again (Cmd+Shift+D to swith to the Debug perspective and just press enter)
```


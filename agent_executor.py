from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from typing import override
from process_engine import submit_workitem

# from src.no_llm_framework.server.agent import Agent


class ProcessAgentExecutor(AgentExecutor):
    """Test AgentProxy Implementation."""

    # def __init__(self):
        # self.agent = Agent(
        #     mode='stream',
        #     token_stream_callback=print,
        #     mcp_url='https://gitmcp.io/google/A2A',
        # )

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        task = context.current_task

        print(task)

        request = {
            "input": query,
            "process_instance_id": "new",
            "activity_id": None,
            "process_definition_id": "contest_submission_evaluation"
        }

        await submit_workitem(request)

        # if not context.message:
        #     raise Exception('No message provided')

        if not task:
            task = new_task(context.message)
            event_queue.enqueue_event(task)

        event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                append=True,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(
                        event['content'],
                        task.contextId,
                        task.id,
                    ),
                ),
                final=False,
                contextId=task.contextId,
                taskId=task.id,
            )
        )

        # async for event in self.agent.stream(query):
        #     if event['is_task_complete']:
        #         event_queue.enqueue_event(
        #             TaskArtifactUpdateEvent(
        #                 append=False,
        #                 contextId=task.contextId,
        #                 taskId=task.id,
        #                 lastChunk=True,
        #                 artifact=new_text_artifact(
        #                     name='current_result',
        #                     description='Result of request to agent.',
        #                     text=event['content'],
        #                 ),
        #             )
        #         )
        #         event_queue.enqueue_event(
        #             TaskStatusUpdateEvent(
        #                 status=TaskStatus(state=TaskState.completed),
        #                 final=True,
        #                 contextId=task.contextId,
        #                 taskId=task.id,
        #             )
        #         )
        #     elif event['require_user_input']:
        #         event_queue.enqueue_event(
        #             TaskStatusUpdateEvent(
        #                 status=TaskStatus(
        #                     state=TaskState.input_required,
        #                     message=new_agent_text_message(
        #                         event['content'],
        #                         task.contextId,
        #                         task.id,
        #                     ),
        #                 ),
        #                 final=True,
        #                 contextId=task.contextId,
        #                 taskId=task.id,
        #             )
        #         )
        #     else:
        #         event_queue.enqueue_event(
        #             TaskStatusUpdateEvent(
        #                 append=True,
        #                 status=TaskStatus(
        #                     state=TaskState.working,
        #                     message=new_agent_text_message(
        #                         event['content'],
        #                         task.contextId,
        #                         task.id,
        #                     ),
        #                 ),
        #                 final=False,
        #                 contextId=task.contextId,
        #                 taskId=task.id,
        #             )
        #         )

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')
    



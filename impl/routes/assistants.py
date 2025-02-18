import asyncio
import time
import logging
from datetime import datetime
from uuid import uuid1
from fastapi import APIRouter, Body, Depends, Path, Query, HTTPException
from impl.astra_vector import CassandraClient
from openapi_server.models.delete_assistant_response import DeleteAssistantResponse
from openapi_server.models.list_assistants_response import ListAssistantsResponse

from .utils import verify_db_client, verify_openai_token
from ..model.assistant_object import AssistantObject
from ..model.assistant_object_tools_inner import AssistantObjectToolsInner
from ..model.create_assistant_request import CreateAssistantRequest
from ..model.modify_assistant_request import ModifyAssistantRequest

router = APIRouter()

logger = logging.getLogger(__name__)

@router.get(
    "/assistants",
    responses={
        200: {"model": ListAssistantsResponse, "description": "OK"},
    },
    tags=["Assistants"],
    summary="Returns a list of assistants.",
    response_model_by_alias=True,
)
async def list_assistants(
    limit: int = Query(
        20,
        description="A limit on the number of objects to be returned. Limit can range between 1 and 100, and the default is 20. ",
    ),
    order: str = Query(
        "desc",
        description="Sort order by the &#x60;created_at&#x60; timestamp of the objects. &#x60;asc&#x60; for ascending order and &#x60;desc&#x60; for descending order. ",
    ),
    after: str = Query(
        None,
        description="A cursor for use in pagination. &#x60;after&#x60; is an object ID that defines your place in the list. For instance, if you make a list request and receive 100 objects, ending with obj_foo, your subsequent call can include after&#x3D;obj_foo in order to fetch the next page of the list. ",
    ),
    before: str = Query(
        None,
        description="A cursor for use in pagination. &#x60;before&#x60; is an object ID that defines your place in the list. For instance, if you make a list request and receive 100 objects, ending with obj_foo, your subsequent call can include before&#x3D;obj_foo in order to fetch the previous page of the list. ",
    ),
    openai_token: str = Depends(verify_openai_token),
    astradb: CassandraClient = Depends(verify_db_client),
) -> ListAssistantsResponse:
    raw_assistants = astradb.selectAllFromTable(table="assistants")

    assistants = []
    if len(raw_assistants) == 0:
        return ListAssistantsResponse(
            data=assistants,
            object="assistant",
            first_id="none",
            last_id="none",
            has_more=False,
        )
    for assistant in raw_assistants:
        created_at = int(assistant["created_at"].timestamp() * 1000)

        metadata = assistant["metadata"]
        if metadata is None:
            metadata = {}

        file_ids = assistant["file_ids"]
        if file_ids is None:
            file_ids = []

        toolsJson = assistant["tools"]
        tools = []

        if toolsJson is not None:
            for json_string in toolsJson:
                tools.append(AssistantObjectToolsInner.parse_raw(json_string))

        if assistant["model"] is None:
            logger.info(f'Model is required, assistant={assistant}, assistant["model"]={assistant["model"]}')

        assistant = AssistantObject(
            id=assistant["id"],
            object="assistant",
            created_at=created_at,
            name=assistant["name"],
            description=assistant["description"],
            model=assistant["model"],
            instructions=assistant["instructions"],
            tools=tools,
            file_ids=file_ids,
            metadata=metadata,
        )
        assistants.append(assistant)
    first_id = raw_assistants[0]["id"]
    last_id = raw_assistants[len(raw_assistants) - 1]["id"]
    assistants_response = ListAssistantsResponse(
        data=assistants,
        object="assistants",
        first_id=first_id,
        last_id=last_id,
        has_more=False,
    )
    return assistants_response


@router.post(
    "/assistants",
    responses={
        200: {"model": AssistantObject, "description": "OK"},
    },
    tags=["Assistants"],
    summary="Create an assistant with a model and instructions.",
    response_model_by_alias=True,
)
async def create_assistant(
    create_assistant_request: CreateAssistantRequest = Body(None, description=""),
    openai_token: str = Depends(verify_openai_token),
    astradb: CassandraClient = Depends(verify_db_client),
) -> AssistantObject:
    assistant_id = str(uuid1())
    logging.info(f"going to create assistant with id: {assistant_id} and details {create_assistant_request}")
    metadata = create_assistant_request.metadata
    if metadata is None:
        metadata = {}

    file_ids = create_assistant_request.file_ids
    if file_ids is None:
        file_ids = []

    tools = create_assistant_request.tools
    if tools is None:
        tools = []

    retrieval_tool = AssistantObjectToolsInner(type='retrieval', function=None)
    if file_ids is not None and retrieval_tool not in tools and file_ids != []:
        # raise http error
        raise HTTPException(status_code=400, detail="Retrieval tool is required when file_ids is not [].")


    description = create_assistant_request.description
    if description is None:
        description = ""

    created_at = int(time.mktime(datetime.now().timetuple()))
    astradb.upsert_assistant(
        id=assistant_id,
        created_at=created_at,
        name=create_assistant_request.name,
        description=description,
        model=create_assistant_request.model,
        instructions=create_assistant_request.instructions,
        tools=tools,
        file_ids=file_ids,
        metadata=metadata,
        object="assistant",
    )
    logging.info(f"created assistant with id: {assistant_id}")

    name = create_assistant_request.name
    if name is None:
        name = ""

    updated_assistant = AssistantObject(
        id=assistant_id,
        created_at=created_at,
        name=name,
        description=description,
        model=create_assistant_request.model,
        instructions=create_assistant_request.instructions,
        tools=tools,
        file_ids=file_ids,
        metadata=metadata,
        object="assistant",
    )
    logging.info(f"with these details: {updated_assistant}")
    return updated_assistant


@router.post("/assistants/{assistant_id}", response_model=AssistantObject)
async def modify_assistant(
    assistant_id: str = Path(..., description="The ID of the assistant to modify."),
    modify_assistant_request: ModifyAssistantRequest = Body(None, description=""),
    openai_token: str = Depends(verify_openai_token),
    astradb: CassandraClient = Depends(verify_db_client),
) -> AssistantObject:
    metadata = modify_assistant_request.metadata
    if metadata is None:
        metadata = {}

    file_ids = modify_assistant_request.file_ids
    if file_ids is None:
        file_ids = []

    tools = modify_assistant_request.tools
    if tools is None:
        tools = []

    description = modify_assistant_request.description
    if description is None:
        description = ""

    assistant = astradb.get_assistant(id=assistant_id)
    if assistant is None:
        logger.warn(f"this should not happen")
        asyncio.sleep(1)
        return modify_assistant(assistant_id, modify_assistant_request, openai_token, astradb)
    logger.info(f'assistant before upsert: {assistant}')

    astradb.upsert_assistant(
        id=assistant_id,
        created_at=int(time.mktime(datetime.now().timetuple())),
        name=modify_assistant_request.name,
        description=description,
        model=modify_assistant_request.model,
        instructions=modify_assistant_request.instructions,
        tools=tools,
        file_ids=file_ids,
        metadata=metadata,
        object="assistant",
    )

    assistant = astradb.get_assistant(id=assistant_id)
    logger.info(f'assistant upserted: {assistant}')
    return assistant


@router.delete(
    "/assistants/{assistant_id}",
    responses={
        200: {"model": DeleteAssistantResponse, "description": "OK"},
    },
    tags=["Assistants"],
    summary="Delete an assistant.",
    response_model_by_alias=True,
)
async def delete_assistant(
    assistant_id: str,
    openai_token: str = Depends(verify_openai_token),
    astradb: CassandraClient = Depends(verify_db_client),
) -> DeleteAssistantResponse:
    astradb.delete_assistant(id=assistant_id)
    return DeleteAssistantResponse(
        id=str(assistant_id), deleted=True, object="assistant"
    )


@router.get(
    "/assistants/{assistant_id}",
    responses={
        200: {"model": AssistantObject, "description": "OK"},
    },
    tags=["Assistants"],
    summary="Retrieves an assistant.",
    response_model_by_alias=True,
)
async def get_assistant(
    assistant_id: str,
    openai_token: str = Depends(verify_openai_token),
    astradb: CassandraClient = Depends(verify_db_client),
) -> AssistantObject:
    assistant = astradb.get_assistant(id=assistant_id)
    if assistant is None:
        raise HTTPException(status_code=404, detail="Assistant not found.")
    return assistant

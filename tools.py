import httpx
import os
import json
from pydantic import BaseModel, Field, EmailStr
from dotenv import load_dotenv

load_dotenv(override=True)

PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


# ---------------------------------------------------------
# 1. Pydantic Models for Tool Schemas
# ---------------------------------------------------------

class RecordUserDetails(BaseModel):
    """Record that a visitor is interested in getting in touch and provided contact info."""
    email: EmailStr = Field(description="The email address provided by the user.")
    name: str = Field(default="Name not provided", description="The user's name, if provided.")
    notes: str = Field(default="Not provided", description="Any additional conversation context worth recording.")

class RecordUnknownQuestion(BaseModel):
    """Always use this tool to record any question about the person that couldn't be answered."""
    question: str = Field(description="The question that couldn't be answered.")


# ---------------------------------------------------------
# 2. Convert Pydantic Models to OpenAI Tool Format
# ---------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "record_user_details",
            "description": RecordUserDetails.__doc__,
            "parameters": RecordUserDetails.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_unknown_question",
            "description": RecordUnknownQuestion.__doc__,
            "parameters": RecordUnknownQuestion.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_background",
            "description": (
                "Load the candidate's full background (skills, experience, education, "
                "certifications, projects, contact details). Call this BEFORE answering "
                "any specific question about the candidate when the answer is not already "
                "in the Identity section. Returns the complete background text."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ---------------------------------------------------------
# 3. Async Tool Implementation & Execution
# ---------------------------------------------------------

async def push_async(text: str):
    """Non-blocking HTTP call to Pushover."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        print(f"[Log] Push skipped (missing credentials): {text}")
        return

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                PUSHOVER_URL,
                data={
                    "token": PUSHOVER_TOKEN,
                    "user": PUSHOVER_USER,
                    "message": text,
                },
                timeout=5.0,
            )
        except Exception as e:
            print(f"[Error] Failed to send push notification: {e}")


async def record_user_details(email: str, name: str = "Name not provided", notes: str = "Not provided"):
    await push_async(f"Recording interest from {name} ({email}). Notes: {notes}")
    return "OK"


async def record_unknown_question(question: str):
    await push_async(f"Unknown question asked: {question}")
    return "OK"


async def retrieve_background() -> str:
    """Return the full background text (CV).

    Loads lazily and caches the background on first use so the env var / file
    is only read once per process. The returned text is deliberately NOT part
    of the system prompt (context minimization); it is fetched on demand.
    """
    from context import load_background

    return load_background()


TOOL_MAP = {
    "record_user_details": record_user_details,
    "record_unknown_question": record_unknown_question,
    "retrieve_background": retrieve_background,
}


async def handle_tool_calls_async(tool_calls):
    results = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        tool_func = TOOL_MAP.get(tool_name)
        if tool_func:
            result = await tool_func(**arguments)
        else:
            result = f"Unknown tool: {tool_name}"

        results.append(
            {"role": "tool", "content": json.dumps(result), "tool_call_id": tool_call.id}
        )
    return results
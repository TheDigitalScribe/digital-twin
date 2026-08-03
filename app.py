import time
from collections import defaultdict
from openai import AsyncOpenAI
from context import TWIN_SYSTEM_PROMPT
from tools import tools, handle_tool_calls_async
from styles import CSS, JS, EXAMPLES
from dotenv import load_dotenv
import gradio as gr
import sys
import os

# Defense-in-depth guardrail layer (heuristic, best-effort).
from security import is_suspicious_request, scrub_output, DECLINE_INPUT

load_dotenv(override=True)

REQUIRED_ENV_VARS = ["OPENAI_API_KEY"]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"❌ CRITICAL ERROR: Missing environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

MODEL_NAME = "gpt-5.4-mini"
openai = AsyncOpenAI()

system = [{"role": "system", "content": TWIN_SYSTEM_PROMPT}]

RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_WINDOW = 60
user_request_history = defaultdict(list)

def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    user_request_history[client_ip] = [
        t for t in user_request_history[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(user_request_history[client_ip]) >= RATE_LIMIT_REQUESTS:
        return True
    user_request_history[client_ip].append(now)
    return False

async def chat(message, history, request: gr.Request):
    client_ip = request.client.host if request and request.client else "127.0.0.1"

    if check_rate_limit(client_ip):
        return "⚠️ You're sending messages too quickly. Please wait a minute before asking another question."

    message_text = message.strip()
    if not message_text:
        return "Please enter a valid question."
    if len(message_text) > 500:
        return "⚠️ Your message is too long (maximum 500 characters)."

    # Layer A: INPUT SANDBOXING — block prompt-injection / extraction attempts
    # before they ever reach the model.
    if is_suspicious_request(message_text):
        print(f"[Security] Input blocked from {client_ip}: suspicious request.")
        return DECLINE_INPUT
    messages = system + history + [{"role": "user", "content": message_text}]
    # Await the API call
    response = await openai.chat.completions.create(model=MODEL_NAME, messages=messages, tools=tools)
    
    while response.choices[0].finish_reason == "tool_calls":
        msg = response.choices[0].message
        tool_calls = msg.tool_calls
        
        # Await async tool handling
        results = await handle_tool_calls_async(tool_calls)
        
        messages.append(msg)
        messages.extend(results)
        response = await openai.chat.completions.create(model=MODEL_NAME, messages=messages, tools=tools)

    reply = response.choices[0].message.content

    # Layer B: OUTPUT SCRUBBING — neutralize any leaked secrets / prompt text
    # before it is shown to the user.
    return scrub_output(reply)

if __name__ == "__main__":
    gr.ChatInterface(
        chat,
        examples=EXAMPLES,
        title="Digital Twin",
        description="Talk to my AI twin about my career",
        chatbot=gr.Chatbot(show_label=False),
    ).queue().launch(css=CSS, js=JS, theme=gr.themes.Base())
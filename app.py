import os
import uuid
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from streaming_utils import stream_sse

# Load environment configuration
load_dotenv()

app = Flask(__name__)

# Model initialization
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME", "DeepSeek-V4-Flash")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")

model = ChatOpenAI(
    model=DEPLOYMENT_NAME,
    base_url=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    streaming=True,
    temperature=0.7,
)

# -------------------------------------------------------------
# Agent Tools with in-tool streaming via get_stream_writer()
# -------------------------------------------------------------
def get_weather(city: str) -> str:
    """Get current weather forecast for a specified city."""
    writer = get_stream_writer()
    if writer:
        writer(f"📡 Querying meteorological satellite for {city}...")
        writer(f"🌡️ Parsing temperature, atmospheric pressure, and radar...")
    return f"The weather in {city} is currently 22°C (72°F) and Mostly Sunny with a light breeze."


def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    writer = get_stream_writer()
    if writer:
        writer(f"🧮 Calculating expression: '{expression}'...")
    try:
        allowed_names = {"abs": abs, "round": round, "min": min, "max": max, "pow": pow}
        result = eval(expression, {"__builtins__": None}, allowed_names)
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"


def search_knowledge_base(query: str) -> str:
    """Search internal enterprise documentation and knowledge base."""
    writer = get_stream_writer()
    if writer:
        writer(f"🔍 Indexing search embeddings for: '{query}'...")
        writer("📄 Scanning relevant articles in GenAI repository...")
    return (
        f"Knowledge Base match for '{query}': LangChain streaming allows real-time token delivery, "
        f"custom events via get_stream_writer(), and agent state updates using stream_mode in LangGraph."
    )


tools = [get_weather, calculator, search_knowledge_base]

# Multi-turn memory checkpointer
checkpointer = InMemorySaver()

# Create LangChain agent
agent = create_agent(
    model=model,
    tools=tools,
    checkpointer=checkpointer,
)


@app.route("/")
def index():
    """Render the chat interface."""
    return render_template("index.html")


@app.route("/stream", methods=["POST"])
@stream_sse
def stream_chat():
    """
    Live streaming chat endpoint.
    Decorated with @stream_sse so the route only needs to return the agent stream!
    Formatting, SSE protocol headers, chunk extraction, and completion signals
    are all handled cleanly by the decorator.
    """
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    thread_id = data.get("thread_id") or str(uuid.uuid4())

    if not user_message:
        return {"type": "error", "message": "Message is required"}

    config = {"configurable": {"thread_id": thread_id}}

    # Return the agent stream directly
    return agent.stream(
        {"messages": [{"role": "user", "content": user_message}]},
        stream_mode=["messages", "updates", "custom"],
        version="v2",
        config=config,
    )


@app.route("/reset", methods=["POST"])
def reset_session():
    """Generates a new session thread_id."""
    new_thread_id = str(uuid.uuid4())
    return jsonify({"thread_id": new_thread_id, "status": "reset"})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

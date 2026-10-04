import json
import functools
from typing import Generator, Any
from flask import Response, stream_with_context
from langchain_core.messages import AIMessageChunk, ToolMessage


def format_sse(event_data: dict) -> str:
    """Formats a Python dictionary as a Server-Sent Events (SSE) data frame."""
    return f"data: {json.dumps(event_data)}\n\n"


def parse_langchain_chunk(chunk: dict) -> Generator[dict, None, None]:
    """
    Translates raw LangGraph/LangChain (version="v2") stream chunks
    into standardized, clean UI events for the frontend.
    
    Yields event dicts such as:
      - {"type": "token", "content": ...}
      - {"type": "reasoning", "content": ...}
      - {"type": "tool_chunk", "name": ..., "args": ...}
      - {"type": "custom", "content": ...}
      - {"type": "tool_result", "tool": ..., "result": ...}
    """
    chunk_type = chunk.get("type")
    chunk_data = chunk.get("data")

    # 1. In-tool custom updates (emitted via get_stream_writer())
    if chunk_type == "custom":
        yield {"type": "custom", "content": str(chunk_data)}

    # 2. Token-level streaming (LLM tokens, reasoning, and tool call chunks)
    elif chunk_type == "messages":
        token, metadata = chunk_data
        if isinstance(token, AIMessageChunk):
            # Extract reasoning/thinking if present
            reasoning = getattr(token, "reasoning", None)
            if not reasoning and hasattr(token, "additional_kwargs"):
                reasoning = token.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield {"type": "reasoning", "content": reasoning}

            # Partial tool call arguments as they are being generated
            if token.tool_call_chunks:
                for tc in token.tool_call_chunks:
                    yield {
                        "type": "tool_chunk",
                        "name": tc.get("name"),
                        "args": tc.get("args"),
                    }

            # Standard text token
            if token.text:
                yield {"type": "token", "content": token.text}

    # 3. Node/Step updates (e.g. tool execution completed)
    elif chunk_type == "updates" and isinstance(chunk_data, dict):
        for node, update in chunk_data.items():
            if node == "tools":
                for msg in update.get("messages", []):
                    if isinstance(msg, ToolMessage):
                        yield {
                            "type": "tool_result",
                            "tool": msg.name,
                            "result": msg.content,
                        }


def stream_sse(func):
    """
    Decorator for Flask streaming endpoints.
    
    The decorated endpoint only needs to return or yield LangChain stream chunks
    or custom event dictionaries. The decorator handles:
      - Preserving request context via stream_with_context
      - Packaging into Flask Response(mimetype='text/event-stream')
      - Appropriate HTTP streaming headers (no-cache, X-Accel-Buffering)
      - Transforming LangChain chunks to UI events
      - SSE formatting (data: {...}\\n\\n)
      - Terminal 'done' event signal
      - Graceful error event handling
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Call the underlying route function while the request context is active
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            def err_gen():
                yield format_sse({"type": "error", "message": str(e)})
            return Response(err_gen(), mimetype="text/event-stream")

        def generate():
            try:
                iterator = result if hasattr(result, "__iter__") else [result]

                for raw_item in iterator:
                    # Case A: Raw LangChain chunk (e.g. from agent.stream(...))
                    if isinstance(raw_item, dict) and "type" in raw_item and "data" in raw_item:
                        for event in parse_langchain_chunk(raw_item):
                            yield format_sse(event)
                    # Case B: Route yielded a custom UI event dict directly
                    elif isinstance(raw_item, dict):
                        yield format_sse(raw_item)
                    # Case C: Route yielded a pre-formatted SSE string
                    elif isinstance(raw_item, str):
                        yield raw_item

                # Final completion event
                yield format_sse({"type": "done"})

            except Exception as e:
                yield format_sse({"type": "error", "message": str(e)})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "text/event-stream",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return wrapper

"""FastAPI main module - API endpoints"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import run_agent
from llm import chat
from tools import read_file, write_file, list_files

app = FastAPI(title="AI Coding Agent", version="0.1.0")


class ChatRequest(BaseModel):
    prompt: str
    model: str = "qwen2.5-coder:7b"


class AgentRequest(BaseModel):
    task: str
    max_iterations: int = 10
    apply: bool = False


class FileReadRequest(BaseModel):
    filepath: str


class FileWriteRequest(BaseModel):
    filepath: str
    content: str


class ListFilesRequest(BaseModel):
    directory: str
    pattern: str = "*"


@app.get("/")
def root():
    return {"status": "ok", "message": "AI Coding Agent API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    """Simple chat with the LLM."""
    try:
        response = chat(request.prompt, request.model)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent")
def agent_endpoint(request: AgentRequest):
    """Run the agent on a task."""
    try:
        result = run_agent(request.task, request.max_iterations, verbose=False, apply=request.apply)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/read")
def read_endpoint(request: FileReadRequest):
    """Read a file."""
    return read_file(request.filepath)


@app.post("/tools/write")
def write_endpoint(request: FileWriteRequest):
    """Write to a file."""
    return write_file(request.filepath, request.content)


@app.post("/tools/list")
def list_endpoint(request: ListFilesRequest):
    """List files in a directory."""
    return list_files(request.directory, request.pattern)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

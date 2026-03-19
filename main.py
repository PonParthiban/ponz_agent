"""FastAPI main module - API endpoints"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import run_agent
from llm import chat
from tools import read_file, write_file, list_files

app = FastAPI(title="AI Coding Agent", version="0.1.0")

# Store pending changes for approval
pending_changes = {}  # {task_id: {"file": path, "content": content, "diff": diff}}


class ChatRequest(BaseModel):
    prompt: str
    model: str = "qwen2.5-coder:7b"


class AgentRequest(BaseModel):
    task: str
    max_iterations: int = 10


class ApproveRequest(BaseModel):
    task_id: str


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
    """Run the agent on a task. Returns diff for approval."""
    import uuid
    try:
        result = run_agent(request.task, request.max_iterations, verbose=False, approve=False)
        
        # If pending approval, store the change
        if result.get("status") == "pending_approval":
            task_id = str(uuid.uuid4())[:8]
            pending_changes[task_id] = {
                "file": result.get("file"),
                "content": result.get("new_content"),
                "diff": result.get("diff"),
                "task": request.task
            }
            result["task_id"] = task_id
            result["approve_url"] = f"POST /approve with task_id: {task_id}"
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/approve")
def approve_endpoint(request: ApproveRequest):
    """Approve and apply pending changes."""
    task_id = request.task_id
    
    if task_id not in pending_changes:
        raise HTTPException(status_code=404, detail=f"No pending changes for task_id: {task_id}")
    
    change = pending_changes.pop(task_id)
    
    # Apply the change
    result = write_file(change["file"], change["content"])
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    
    return {
        "success": True,
        "status": "applied",
        "file": change["file"],
        "diff": change["diff"],
        "message": f"Changes applied to {change['file']}"
    }


@app.get("/pending")
def pending_endpoint():
    """List all pending changes awaiting approval."""
    return {
        "pending": [
            {"task_id": tid, "file": data["file"], "task": data["task"]}
            for tid, data in pending_changes.items()
        ]
    }


@app.delete("/pending/{task_id}")
def reject_endpoint(task_id: str):
    """Reject/discard pending changes."""
    if task_id not in pending_changes:
        raise HTTPException(status_code=404, detail=f"No pending changes for task_id: {task_id}")
    
    change = pending_changes.pop(task_id)
    return {
        "success": True,
        "status": "rejected",
        "file": change["file"],
        "message": "Changes discarded"
    }


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

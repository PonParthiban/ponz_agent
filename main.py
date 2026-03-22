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
    files: list[str] | None = None  # Optional: partial approval - only apply these files


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
    """Run the agent on a task. Returns diff for approval (supports multi-file batch)."""
    import uuid
    try:
        result = run_agent(request.task, request.max_iterations, verbose=False, approve=False)
        
        # If pending approval, store the change(s)
        if result.get("status") == "pending_approval":
            task_id = str(uuid.uuid4())[:8]
            
            # Agent now always returns "files" array
            files_data = result.get("files", [])
            
            # Store internally
            pending_changes[task_id] = {
                "files": files_data,
                "task": request.task
            }
            
            # Return structured multi-file response
            return {
                "status": "pending_approval",
                "task_id": task_id,
                "files": [
                    {"file": f["file"], "diff": f.get("diff", "")}
                    for f in files_data
                ],
                "file_count": len(files_data),
                "message": f"Review {len(files_data)} file(s) and POST /approve with task_id: {task_id}"
            }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/approve")
def approve_endpoint(request: ApproveRequest):
    """Approve and apply pending changes (supports multi-file batch and partial approval)."""
    task_id = request.task_id
    
    if task_id not in pending_changes:
        raise HTTPException(status_code=404, detail=f"No pending changes for task_id: {task_id}")
    
    change = pending_changes[task_id]
    all_files = change.get("files", [])
    
    # Partial approval: filter to requested files only
    if request.files:
        files_to_apply = [f for f in all_files if f.get("file") in request.files]
        remaining_files = [f for f in all_files if f.get("file") not in request.files]
    else:
        files_to_apply = all_files
        remaining_files = []
    
    applied = []
    errors = []
    
    # Apply selected files
    for f in files_to_apply:
        filepath = f.get("file")
        content = f.get("content")
        
        result = write_file(filepath, content)
        
        if result.get("success"):
            applied.append(filepath)
        else:
            errors.append({
                "file": filepath,
                "error": result.get("error")
            })
    
    # Update or remove pending changes
    if remaining_files:
        pending_changes[task_id]["files"] = remaining_files
    else:
        pending_changes.pop(task_id)
    
    return {
        "status": "applied" if not errors else "partial",
        "task_id": task_id,
        "files": applied,
        "file_count": len(applied),
        "errors": errors if errors else None,
        "remaining": len(remaining_files) if remaining_files else None,
        "message": f"Applied changes to {len(applied)} file(s)"
    }


@app.get("/pending")
def pending_endpoint():
    """List all pending changes awaiting approval."""
    return {
        "pending": [
            {
                "task_id": tid,
                "files": [f["file"] for f in data.get("files", [])],
                "file_count": len(data.get("files", [])),
                "task": data["task"]
            }
            for tid, data in pending_changes.items()
        ]
    }


@app.delete("/pending/{task_id}")
def reject_endpoint(task_id: str):
    """Reject/discard pending changes."""
    if task_id not in pending_changes:
        raise HTTPException(status_code=404, detail=f"No pending changes for task_id: {task_id}")
    
    change = pending_changes.pop(task_id)
    files = [f["file"] for f in change.get("files", [])]
    return {
        "success": True,
        "status": "rejected",
        "files": files,
        "message": f"Discarded changes to {len(files)} file(s)"
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

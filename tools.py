"""Tools module - file operations for the agent"""
from pathlib import Path


def read_file(filepath: str) -> dict:
    """Read a file and return its contents."""
    try:
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}
        if not path.is_file():
            return {"success": False, "error": f"Not a file: {filepath}"}
        
        content = path.read_text()
        return {"success": True, "content": content, "path": str(path.absolute())}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(filepath: str, content: str) -> dict:
    """Write content to a file."""
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"success": True, "path": str(path.absolute())}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(directory: str, pattern: str = "*") -> dict:
    """List files in a directory."""
    try:
        path = Path(directory)
        if not path.exists():
            return {"success": False, "error": f"Directory not found: {directory}"}
        if not path.is_dir():
            return {"success": False, "error": f"Not a directory: {directory}"}
        
        files = [str(f.relative_to(path)) for f in path.rglob(pattern) if f.is_file()]
        return {"success": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Tool definitions for the agent
TOOLS = {
    "read_file": {
        "function": read_file,
        "description": "Read contents of a file",
        "parameters": ["filepath"]
    },
    "write_file": {
        "function": write_file,
        "description": "Write content to a file",
        "parameters": ["filepath", "content"]
    },
    "list_files": {
        "function": list_files,
        "description": "List files in a directory",
        "parameters": ["directory", "pattern"]
    }
}


if __name__ == "__main__":
    # Quick test
    print("Testing tools...")
    print(read_file(__file__))
    print(list_files(".", "*.py"))

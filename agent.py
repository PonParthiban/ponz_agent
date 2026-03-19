"""Agent module - core agent logic with structured JSON tool calling"""
import json
import re
from llm import chat
from tools import TOOLS


def extract_filename_from_task(task: str) -> str | None:
    """Extract filename mentioned in task."""
    # Match patterns like "test.py", "main.py", "/path/to/file.py"
    match = re.search(r'[\w/\\.-]+\.py\b', task, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def is_multi_file_task(task: str) -> bool:
    """Check if task requires processing multiple files."""
    keywords = ["all files", "all python", "every file", "the project", "entire project", "whole project"]
    return any(kw in task.lower() for kw in keywords)


def match_file(filename: str, files: list[str]) -> str | None:
    """Find best matching file from list."""
    filename_lower = filename.lower()
    base_name = filename_lower.split("/")[-1].split("\\")[-1]
    
    # Exact match
    for f in files:
        if f.lower() == filename_lower or f.lower().endswith("/" + filename_lower):
            return f
    
    # Basename match
    for f in files:
        f_base = f.lower().split("/")[-1].split("\\")[-1]
        if f_base == base_name:
            return f
    
    # Partial match (filename without extension)
    stem = base_name.replace(".py", "")
    for f in files:
        if stem in f.lower():
            return f
    
    return None

SYSTEM_PROMPT = """You are a coding assistant agent. You MUST respond with valid JSON only.

Available tools:
- read_file: Read contents of a file. Input: {"path": "filepath"}
- write_file: Write content to a file. Input: {"path": "filepath", "content": "text"}
- list_files: List files in directory. Input: {"directory": "path", "pattern": "*.py"}

Response format (ALWAYS use this exact JSON structure):

When using a tool:
{
  "thought": "your reasoning about what to do next",
  "action": "tool_name",
  "input": {"param": "value"}
}

When finished with changes:
{
  "thought": "summary of what was done",
  "action": "final_answer",
  "output": "your final answer to the user"
}

When NO changes needed:
{
  "thought": "why no changes are needed",
  "action": "no_change",
  "output": "explanation of why code is already acceptable"
}

CRITICAL RULES:

1. FILE SELECTION LOGIC:
   - If task contains a FULL PATH (e.g., "/home/user/test.py") → read_file directly
   - If task contains only FILENAME (e.g., "test.py", "main.py"):
     * First use list_files to find matching files
     * Select the file whose name best matches the task keyword
     * Then read_file on that specific file
   - If task says "all files" or "the project" → list_files first, then process relevant ones
   
   FILE MATCHING PRIORITY:
   - Exact filename match: task says "test.py" → choose "test.py"
   - Partial match: task says "test" → prefer "test.py" over "main.py"
   - Extension match: task says "Python files" → choose *.py files

2. READ BEFORE WRITE:
   - If a task mentions a specific file → ALWAYS use read_file FIRST
   - NEVER assume a file does not exist
   - NEVER write without reading first

3. AUTOMATIC SYNTAX CHECK:
   When you read a Python file, the system AUTOMATICALLY runs syntax validation.
   You will see "SYNTAX CHECK (automatic)" in the tool result.
   
   USE THIS RESULT TO DECIDE:
   - If valid=false → YOU MUST FIX THE CODE (use write_file)
   - If valid=true → decide improvement or no_change
   
   You do NOT need to call check_syntax yourself - it happens automatically.
   But you MUST respect the result!

4. DECIDE: MODIFY OR NO_CHANGE:
   
   *** DECISION PRIORITY (follow this order) ***
   
   STEP 1: CHECK FOR CRITICAL ERRORS FIRST
   Ask: "Will this code run without crashing?"
   
   CRITICAL ERRORS (MUST FIX - no_change is FORBIDDEN):
   - Syntax errors (missing colons, brackets, quotes, commas)
   - Indentation errors (wrong indent level, mixed tabs/spaces)
   - Invalid imports (typos, wrong module names)
   - NameError risks (undefined variables)
   - Code that would raise an exception when executed
   
   If ANY critical error exists → STOP → MUST use write_file to fix
   NEVER return no_change if code has execution errors!
   
   STEP 2: ONLY IF CODE IS VALID, CHECK QUALITY
   Quality issues (optional - may use no_change):
   - Missing type hints
   - Missing docstrings
   - Minor formatting issues
   - Style preferences
   
   NO_CHANGE is allowed ONLY when:
   - Code runs correctly (no syntax/runtime errors)
   - Code is properly indented
   - No obvious bugs
   
   *** VERIFICATION BEFORE DECIDING ***
   Before choosing no_change, mentally run the code:
   1. Would "python filename.py" succeed? If NO → MUST FIX
   2. Would "import filename" work? If NO → MUST FIX
   3. Are all colons, brackets, quotes balanced? If NO → MUST FIX
   
   EXAMPLES:
   - "def add(a,b) return a+b" → MUST FIX (syntax error: missing colon)
   - "def add(a,b):\nreturn a+b" → MUST FIX (indentation error: return not indented)
   - "import numpyy" → MUST FIX (invalid import)
   - "x = [1, 2, 3" → MUST FIX (unclosed bracket)
   - "def add(a,b):return a+b" → MAY FIX (valid but poor style)
   - "def add(a: int, b: int) -> int:\n    '''Add.'''\n    return a + b" → NO_CHANGE OK

4. MINIMAL IMPROVEMENT PRINCIPLE:
   - Prefer SMALL, LOCAL changes over large rewrites
   - Keep the original simplicity - do not expand simple code into complex systems
   - If input is 5 lines, output should be ~5-10 lines, NOT 50 lines
   - Do NOT introduce frameworks, patterns, or abstractions unless explicitly asked

5. STRUCTURE PRESERVATION (ABSOLUTE - NEVER VIOLATE):
   - Input structure MUST equal output structure:
     * function → function (same name, same params)
     * class → class (same name)
     * script → script
   - NEVER convert between types (function → class, script → unittest)
   - NEVER add new functions, classes, or imports beyond what exists
   
   VIOLATIONS (NEVER DO):
   - def add(a,b) → import unittest... (WRONG: added framework)
   - def add(a,b) → class Calculator... (WRONG: changed to class)
   - def add(a,b) → def addition(x,y)... (WRONG: changed name)
   - 5-line function → 50-line module (WRONG: over-expanded)

4. ALLOWED IMPROVEMENTS ONLY:
   - Type hints: def add(a,b) → def add(a: int, b: int) -> int
   - Docstring: add a brief description
   - Formatting: spaces, indentation, line breaks
   - Fix bugs: if logic is wrong, fix it minimally
   - Simplify: reduce complexity if possible
   
   FORBIDDEN:
   - unittest, pytest, any testing framework
   - New functions or helper methods
   - Example usage, main blocks, demo code
   - Design patterns (factory, singleton, etc.)
   - Error handling beyond what exists (unless broken)

6. WORKFLOW:
   For SPECIFIC FILE (full path given):
     Step 1: read_file directly
     Step 2: improve
     Step 3: write_file
     Step 4: final_answer
   
   For FILENAME ONLY (e.g., "improve test.py"):
     Step 1: list_files to find the file
     Step 2: In thought: "Found [files]. Task mentions [X], selecting [path]."
     Step 3: read_file on selected path
     Step 4: improve and write_file
     Step 5: final_answer

7. SIZE CHECK:
   - Input: 1 function → Output: 1 function
   - Input: ~10 lines → Output: ~10-15 lines (NOT 50+)
   - If you find yourself writing much more code, STOP - you are over-engineering

8. CORRECT EXAMPLE:
   Input:  def add(a,b): return a+b
   Output: def add(a: int, b: int) -> int:
               \"\"\"Add two numbers.\"\"\"
               return a + b
   (4 lines in, 4 lines out - minimal improvement)

8. Output rules:
   - ONLY output valid JSON
   - Tool names: read_file, write_file, list_files, final_answer"""


def parse_response(response: str) -> dict | None:
    try:
        return json.loads(response.strip())
    except:
        pass

    patterns = [r'```json\s*(.*?)```', r'```\s*(.*?)```']
    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                continue

    return None


def execute_tool(action: str, inputs: dict) -> dict:
    tool_map = {
        "read_file": ("read_file", {"filepath": inputs.get("path")}),
        "write_file": ("write_file", {"filepath": inputs.get("path"), "content": inputs.get("content")}),
        "list_files": ("list_files", {"directory": inputs.get("directory", "."), "pattern": inputs.get("pattern", "*")}),
    }

    if action not in tool_map:
        return {"success": False, "error": f"Unknown tool: {action}"}

    name, args = tool_map[action]
    try:
        return TOOLS[name]["function"](**args)
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_agent(task: str, max_iterations: int = 5, verbose: bool = True) -> dict:
    # File selection context
    mentioned_file = extract_filename_from_task(task)
    multi_file = is_multi_file_task(task)
    files_to_process = []
    processed_files = []
    
    # Build initial context with file hints
    file_hint = ""
    if mentioned_file:
        file_hint = f"\n\nHINT: Task mentions file '{mentioned_file}' - prioritize this file."
    elif multi_file:
        file_hint = "\n\nHINT: This is a multi-file task. Use list_files first, then process each relevant file."
    
    messages = [f"{SYSTEM_PROMPT}\n\nTask: {task}{file_hint}"]
    history = []
    last_syntax_valid = True  # Track syntax state across iterations

    for i in range(max_iterations):

        context = "\n\n".join(messages)
        response = chat(context)

        parsed = parse_response(response)
        if not parsed:
            messages.append("Error: respond in valid JSON")
            continue

        action = parsed.get("action")
        thought = parsed.get("thought", "")
        inputs = parsed.get("input", {})

        history.append({"step": i + 1, "action": action, "thought": thought})

        # 🔥 FINAL ANSWER
        if action == "final_answer":
            if last_syntax_valid is False:
                messages.append(
                    "Error: Code has syntax errors. You cannot finish. You MUST fix it using write_file."
                )
                continue
            return {
                "success": True,
                "output": parsed.get("output", ""),
                "history": history
            }

        # 🔥 NO CHANGE (ENFORCED)
        if action == "no_change":
            if last_syntax_valid is False:
                messages.append(
                    "Error: Code has syntax errors. 'no_change' is NOT allowed. You MUST fix it using write_file."
                )
                continue

            return {
                "success": True,
                "output": parsed.get("output", ""),
                "history": history,
                "modified": False
            }

        # 🔥 FORCE FIX MODE - block all actions except write_file when syntax invalid
        if last_syntax_valid is False and action != "write_file":
            messages.append(
                "Error: Syntax is invalid. You MUST use write_file to fix the code."
            )
            continue

        # 🔧 EXECUTE TOOL
        result = execute_tool(action, inputs)

        if not result.get("success"):
            messages.append(f"Tool error: {result.get('error')}")
            continue

        # 🔥 FILE SELECTION ENHANCEMENT
        file_selection_hint = ""
        if action == "list_files":
            files = result.get("files", [])
            if files:
                # Store for multi-file processing
                if multi_file:
                    files_to_process = [f for f in files if f.endswith(".py")]
                    file_selection_hint = f"\nMulti-file task: process these files one by one: {files_to_process}"
                elif mentioned_file:
                    # Find best match
                    best = match_file(mentioned_file, files)
                    if best:
                        file_selection_hint = f"\nBest match for '{mentioned_file}': {best} - use this file."
                    else:
                        file_selection_hint = f"\nNo exact match for '{mentioned_file}'. Available: {files}"

        # 🔥 AUTO SYNTAX CHECK
        syntax_info = ""

        if action == "read_file":
            filepath = inputs.get("path", "")
            # Track processed files for multi-file tasks
            if filepath not in processed_files:
                processed_files.append(filepath)
            if filepath.endswith(".py"):
                content = result.get("content", "")
                syntax = TOOLS["check_syntax"]["function"](content)

                last_syntax_valid = syntax.get("valid", True)

                syntax_info = f"\nSYNTAX: {json.dumps(syntax)}"

                if not last_syntax_valid:
                    syntax_info += "\n*** SYNTAX INVALID - YOU MUST FIX WITH write_file ***"
                else:
                    syntax_info += "\nSyntax OK"

        # Re-check syntax after write_file by RE-READING the file
        if action == "write_file":
            filepath = inputs.get("path", "")
            if filepath.endswith(".py"):
                # Re-read file from disk to verify
                read_result = TOOLS["read_file"]["function"](filepath)
                if read_result.get("success"):
                    content = read_result.get("content", "")
                    syntax = TOOLS["check_syntax"]["function"](content)
                    last_syntax_valid = syntax.get("valid", True)
                    print(f"POST-WRITE SYNTAX: {syntax}")
                    if not last_syntax_valid:
                        syntax_info = f"\nSYNTAX AFTER WRITE: {json.dumps(syntax)}\n*** STILL INVALID - FIX AGAIN ***"
                    else:
                        syntax_info = "\nSYNTAX AFTER WRITE: valid"
            else:
                last_syntax_valid = True

        messages.append(
            f"{response}\n\nRESULT:\n{json.dumps(result)}{syntax_info}{file_selection_hint}"
        )

    return {
        "success": False,
        "error": "Max iterations reached",
        "history": history
    }


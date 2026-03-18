"""Agent module - core agent logic with structured JSON tool calling"""
import json
import re
from llm import chat
from tools import TOOLS

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

When finished:
{
  "thought": "summary of what was done",
  "action": "final_answer",
  "output": "your final answer to the user"
}

CRITICAL RULES:

1. READ BEFORE WRITE:
   - If a task mentions a specific file → ALWAYS use read_file FIRST
   - NEVER assume a file does not exist
   - NEVER write without reading first

2. MINIMAL IMPROVEMENT PRINCIPLE:
   - Prefer SMALL, LOCAL changes over large rewrites
   - Keep the original simplicity - do not expand simple code into complex systems
   - If input is 5 lines, output should be ~5-10 lines, NOT 50 lines
   - Do NOT introduce frameworks, patterns, or abstractions unless explicitly asked

3. STRUCTURE PRESERVATION (ABSOLUTE - NEVER VIOLATE):
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

5. WORKFLOW:
   Step 1: read_file
   Step 2: In thought: "This is [type] named [X] doing [Y]. Minimal improvements: types, docstring, formatting."
   Step 3: write_file with improved version (same structure, same size)
   Step 4: final_answer listing specific small changes

6. SIZE CHECK:
   - Input: 1 function → Output: 1 function
   - Input: ~10 lines → Output: ~10-15 lines (NOT 50+)
   - If you find yourself writing much more code, STOP - you are over-engineering

7. CORRECT EXAMPLE:
   Input:  def add(a,b): return a+b
   Output: def add(a: int, b: int) -> int:
               \"\"\"Add two numbers.\"\"\"
               return a + b
   (4 lines in, 4 lines out - minimal improvement)

8. Output rules:
   - ONLY output valid JSON
   - Tool names: read_file, write_file, list_files, final_answer"""


def parse_response(response: str) -> dict | None:
    """Parse structured JSON response from LLM."""
    # Try direct JSON parse
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from markdown code block
    patterns = [
        r'```json\s*\n?(.*?)\n?```',
        r'```\s*\n?(.*?)\n?```',
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                # Try fixing common JSON issues
                fixed = fix_json_string(match.group(1))
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue
    
    # Try to find JSON object (greedy match for nested braces)
    try:
        start = response.find('{')
        if start != -1:
            depth = 0
            for i, c in enumerate(response[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = response[start:i+1]
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            fixed = fix_json_string(json_str)
                            return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    return None


def fix_json_string(s: str) -> str:
    """Fix common JSON issues from LLM output."""
    result = []
    in_string = False
    escape_next = False
    i = 0
    
    while i < len(s):
        char = s[i]
        
        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue
        
        if char == '\\':
            result.append(char)
            escape_next = True
            i += 1
            continue
        
        if char == '"' and not in_string:
            in_string = True
            result.append(char)
            i += 1
            continue
        
        if char == '"' and in_string:
            # Check if this closes the string or is part of triple quotes
            if i + 2 < len(s) and s[i:i+3] == '"""':
                # Triple quote inside string - escape all three
                result.append('\\"\\"\\"')
                i += 3
                continue
            else:
                # Check if next char suggests string continues (likely unescaped quote)
                next_char = s[i+1] if i + 1 < len(s) else ''
                if next_char not in [',', '}', ']', ':', '\n', ' ', '']:
                    result.append('\\"')
                    i += 1
                    continue
                in_string = False
                result.append(char)
                i += 1
                continue
        
        if in_string:
            if char == '\n':
                result.append('\\n')
            elif char == '\t':
                result.append('\\t')
            else:
                result.append(char)
        else:
            result.append(char)
        i += 1
    
    return ''.join(result)


def execute_tool(action: str, inputs: dict) -> dict:
    """Execute a tool and return the result."""
    # Map action to tool with correct parameter names
    tool_map = {
        "read_file": ("read_file", {"filepath": inputs.get("path", inputs.get("filepath"))}),
        "write_file": ("write_file", {"filepath": inputs.get("path", inputs.get("filepath")), "content": inputs.get("content")}),
        "list_files": ("list_files", {"directory": inputs.get("directory", "."), "pattern": inputs.get("pattern", "*")})
    }
    
    if action not in tool_map:
        return {"success": False, "error": f"Unknown tool: {action}"}
    
    tool_name, args = tool_map[action]
    tool = TOOLS[tool_name]
    
    try:
        return tool["function"](**args)
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_agent(task: str, max_iterations: int = 5, verbose: bool = True) -> dict:
    """Run the agent loop for a given task."""
    messages = [f"{SYSTEM_PROMPT}\n\nTask: {task}"]
    history = []
    
    for i in range(max_iterations):
        if verbose:
            print(f"\n--- Step {i + 1}/{max_iterations} ---")
        
        # Get LLM response
        context = "\n\n".join(messages)
        response = chat(context)
        
        if verbose:
            print(f"Raw: {response[:300]}...")
        
        # Parse JSON response
        parsed = parse_response(response)
        
        if not parsed:
            # Retry once asking for valid JSON
            messages.append(f"Assistant: {response}\n\nError: Invalid JSON. Please respond with valid JSON only.")
            continue
        
        thought = parsed.get("thought", "")
        action = parsed.get("action", "")
        
        if verbose:
            print(f"Thought: {thought}")
            print(f"Action: {action}")
        
        history.append({"step": i + 1, "thought": thought, "action": action, "raw": response})
        
        # Check for final answer
        if action == "final_answer":
            return {
                "success": True,
                "output": parsed.get("output", ""),
                "thought": thought,
                "iterations": i + 1,
                "history": history
            }
        
        # Validate action
        if action not in ["read_file", "write_file", "list_files"]:
            messages.append(f"Assistant: {response}\n\nError: Unknown action '{action}'. Use: read_file, write_file, list_files, or final_answer.")
            continue
        
        # Execute tool
        inputs = parsed.get("input", {})
        if not inputs:
            messages.append(f"Assistant: {response}\n\nError: Missing 'input' field. Provide input parameters.")
            continue
        
        result = execute_tool(action, inputs)
        
        if verbose:
            result_str = json.dumps(result)
            print(f"Result: {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
        
        history[-1]["result"] = result
        
        # If tool failed, include error in context
        if not result.get("success"):
            messages.append(f"Assistant: {response}\n\nTool Error: {result.get('error', 'Unknown error')}. Try again.")
            continue
        
        # Add to context for next iteration
        messages.append(f"Assistant: {response}\n\nTool Result:\n{json.dumps(result)}\n\nContinue with your next step.")
    
    return {
        "success": False,
        "error": "Max iterations reached",
        "iterations": max_iterations,
        "history": history
    }


if __name__ == "__main__":
    print("Testing structured agent...")
    result = run_agent("List all Python files in the current directory and summarize what each one does based on filename.")
    print(f"\n{'='*50}")
    print(f"Success: {result['success']}")
    print(f"Iterations: {result['iterations']}")
    if result['success']:
        print(f"Output: {result['output']}")

import json
import os
import re
from typing import List
from diff_match_patch import diff_match_patch
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langgraph.constants import END, START
from langgraph.graph import  StateGraph
from helpers.prompts import markdown_to_prompt_template
from agent.developer.state import SoftwareDeveloperState, Diffs
from langgraph.prebuilt import ToolNode
from agent.tools.search import search_tools
from agent.tools.codemap import codemap_tools
from agent.tools.write import get_files_structure
# Load the extract diff prompt
extract_diffs_tasks_prompt = markdown_to_prompt_template("agent/developer/prompts/create_diff_prompt.md")
implement_diffs_prompt = markdown_to_prompt_template("agent/developer/prompts/implement_diff.md")
implement_new_file_prompt = markdown_to_prompt_template("agent/developer/prompts/implement_new_file.md")

# Create the runnable with the prompt and model
extract_diff_runnable = extract_diffs_tasks_prompt | ChatGoogleGenerativeAI(model="gemini-2.5-pro-preview-06-05") | StrOutputParser()
edit_according_to_diff_runnable = implement_diffs_prompt | ChatGoogleGenerativeAI(model="gemini-2.5-pro-preview-06-05") | StrOutputParser()
create_new_file_runnable = implement_new_file_prompt | ChatGoogleGenerativeAI(model="gemini-2.5-pro-preview-06-05") | StrOutputParser()

# Load the get clear implementation plan prompt
get_clear_implementation_plan_prompt = markdown_to_prompt_template("agent/developer/prompts/get_clear_implementation_plan.md")

# Create the runnable with the prompt and model
get_clear_implementation_plan_runnable = get_clear_implementation_plan_prompt | ChatGoogleGenerativeAI(model="gemini-2.5-pro-preview-06-05").bind_tools(search_tools+codemap_tools)
dmp = diff_match_patch()
def start_implementing(state: SoftwareDeveloperState):
    return {
        "current_task_idx": 0,
        "current_atomic_task_idx": 0
    }


def proceed_to_next_atomic_task(state: SoftwareDeveloperState):
    # Get current indices
    current_task_idx = state.current_task_idx
    current_atomic_task_idx = state.current_atomic_task_idx
    
    # Get the implementation plan
    plan = state.implementation_plan
    
    # Get current task
    current_task = plan.tasks[current_task_idx]
    atomic_tasks = current_task.atomic_tasks
    
    # If we've completed all atomic tasks in current task
    if current_atomic_task_idx >= len(atomic_tasks) - 1:
        # Move to next main task and reset atomic task index
        return {
            "current_task_idx": current_task_idx + 1,
            "current_atomic_task_idx": 0
        }
    # Otherwise, move to next atomic task
    return {
        "current_task_idx": current_task_idx,
        "current_atomic_task_idx": current_atomic_task_idx + 1
    }


def get_clear_implementation_plan_for_atomic_task(state: SoftwareDeveloperState):
    current_task = state.implementation_plan.tasks[state.current_task_idx]
    current_atomic_task = current_task.atomic_tasks[state.current_atomic_task_idx]
    result = get_clear_implementation_plan_runnable.invoke({
        "development_task": current_atomic_task.atomic_task,
        "file_content": state.current_file_content,
        "target_file": current_task.file_path,
        "codebase_structure": state.codebase_structure,
        "additional_context": current_atomic_task.additional_context,
        "atomic_implementation_research": state.atomic_implementation_research
    })
    return {"atomic_implementation_research": [result]}

def should_continue_implementation_research(state: SoftwareDeveloperState):
    """Router function to determine if tools should be called"""
    last_research_step = state.atomic_implementation_research[-1]

    if last_research_step.tool_calls:
        return "should_continue_research"

    return "implement_plan"


def prepare_for_implementation(state: SoftwareDeveloperState):
    """Read the code file content (if not new) and reset the research"""
    current_task = state.implementation_plan.tasks[state.current_task_idx]
    try:
        with open(current_task.file_path, "r") as file:
            file_content = file.read()
    except FileNotFoundError:
        file_content = "This is a new file"

    return {"current_file_content": file_content,
            "codebase_structure": get_files_structure.invoke({"directory": "./workspace_repo"}),
            "atomic_implementation_research": None}


def is_implementation_complete(state: SoftwareDeveloperState):
    """
    Check if we've completed all implementation tasks.
    """
    current_task_idx = state.current_task_idx
    plan = state.implementation_plan
    return END if current_task_idx >= len(plan.tasks) else "continue"

def convert_tools_messages_to_ai_and_human(implementation_research_scratchpad: List[AnyMessage]):
    messages = []
    for message in implementation_research_scratchpad:
        if message.type == "ai":
            if message.tool_calls:
                tool_name = message.tool_calls[0]["name"]
                tool_args = json.dumps(message.tool_calls[0]["args"])
                messages.append(AIMessage(content=f"I want to call the tool {tool_name} with the following arguments: {tool_args}"))
            else:
                messages.append(message)
        elif message.type == "tool":
            messages.append(HumanMessage(content=f"When executing Tool {message.name} \n The result was {message.content} was called"))
        else:
            messages.append(message)
    return messages

def creating_diffs_for_task(state: SoftwareDeveloperState):
    # Get current task information
    current_task = state.implementation_plan.tasks[state.current_task_idx]
    current_atomic_task = current_task.atomic_tasks[state.current_atomic_task_idx]
    file_path = current_task.file_path

    # check if file is new
    if not os.path.exists(file_path):
        new_file_content = create_new_file_runnable.invoke({
            "task": current_atomic_task.atomic_task,
            "additional_context": current_atomic_task.additional_context,
            "research": convert_tools_messages_to_ai_and_human(state.atomic_implementation_research),
            "file_path": file_path
        })
        with open(file_path, "w") as file:
            file.write(new_file_content)
            file.flush()
    else:
        # Get the diffs
        with open(file_path, "r") as file:
            file_content = file.read()
        # add line numbers
        lines = []
        for i, line in enumerate(file_content.splitlines(), start=1):
            lines.append(f"{i}| {line}")
        file_content = "\n".join(lines)

        diffs_tasks = extract_diff_runnable.invoke({
            "task": current_atomic_task.atomic_task,
            "additional_context": current_atomic_task.additional_context,
            "research": convert_tools_messages_to_ai_and_human(state.atomic_implementation_research),
            "file_path": file_path,
            "file_content": file_content,
            "output_format": JsonOutputParser(pydantic_object=Diffs).get_format_instructions()
        })
        # Find all content between <code_change_request> and </code_change_request>
        blocks = re.findall(
            r"<code_change_request>(.*?)</code_change_request>", diffs_tasks, re.DOTALL
        )

        for block in blocks:
            # Use regex to extract the original code snippet and the task description.
            # The re.DOTALL flag allows the dot (.) to match newline characters.
            match = re.search(
                r"original_code_snippet:\s*(.*?)\s*edit_code_snippet:\s*(.*)",
                block,
                re.DOTALL,
            )
            if match:
                with open(file_path, "r") as f:
                    file_content = f.read()
                original_code = match.group(1).strip()
                edited_code = match.group(2).strip()
                orig_lines = original_code.splitlines()
                first_line = int(orig_lines[0].split("|")[0].strip())
                last_line = int(orig_lines[-1].split("|")[0].strip())
                new_content = file_content.splitlines()
                new_content = (
                    new_content[: first_line - 1]
                    + edited_code.splitlines()
                    + new_content[last_line:]
                )
                with open(file_path, "w") as f:
                    f.write("\n".join(new_content))
                    f.flush()

# Create tool node
research_tool_node = ToolNode(search_tools + codemap_tools, messages_key="atomic_implementation_research")

# Create the workflow graph
workflow = StateGraph(SoftwareDeveloperState)

# Add nodes
workflow.add_node("start_implementing", start_implementing)
workflow.add_node("prepare_for_implementation", prepare_for_implementation)
workflow.add_node("proceed_to_next_atomic_task", proceed_to_next_atomic_task)
workflow.add_node("get_clear_implementation_plan_for_atomic_task", get_clear_implementation_plan_for_atomic_task)
workflow.add_node("research_tool_node", research_tool_node )
workflow.add_node("creating_diffs_for_task", creating_diffs_for_task)

# Add edges
# Reset the system and load the file from the context of atomic task (if not new file)
workflow.add_edge(START, "start_implementing")
# Read file content and reset previous implementation research
workflow.add_edge("start_implementing", "prepare_for_implementation")
# Go to research about how to implement the atomic task
workflow.add_edge("prepare_for_implementation", "get_clear_implementation_plan_for_atomic_task")
# Check if research is done or we should continue research
workflow.add_conditional_edges(
    "get_clear_implementation_plan_for_atomic_task",
    should_continue_implementation_research,
    {
        "should_continue_research": "research_tool_node",
        "implement_plan": "creating_diffs_for_task"
    }
)
# Go back from executing a research tool to research about implementation
workflow.add_edge("research_tool_node", "get_clear_implementation_plan_for_atomic_task")
# After the research lets apply the diffs
workflow.add_edge("creating_diffs_for_task", "proceed_to_next_atomic_task")
# If next atomic task exists rest and go back to research if not end as everything was implemented
workflow.add_conditional_edges(
    "proceed_to_next_atomic_task",
    is_implementation_complete,
    {
        "continue": "prepare_for_implementation",
        END: END
    }
)

# Compile the workflow
swe_developer = workflow.compile().with_config({"tags": ["developer-agent-v3"]})

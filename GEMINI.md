# GEMINI.md

This file provides guidance when working with Google Gemini in this repository.

## Project Overview

SWE Agent Gemini is an AI-powered software engineering agent built with LangGraph that automates code implementation. It uses a two-stage workflow with an Architect agent for research/planning and a Developer agent for implementation.

## Essential Commands

```bash
# Environment setup
uv sync                    # Install all dependencies
cp .env.example .env       # Configure environment variables
source .venv/bin/activate  # Activate virtual environment

# Run the agent
langgraph dev              # Start the LangGraph development server

# Code quality checks (run before commits)
uv run black .             # Format code
uv run isort .             # Sort imports
uv run mypy agent/         # Type checking
uv run flake8 agent/       # Linting

# Testing
uv run pytest              # Run tests (no tests exist yet)
```

## Architecture Overview

The system follows a multi-agent workflow pattern:

1. **Main Orchestrator** (`agent/graph.py`): Routes requests between Architect and Developer
2. **Architect Agent** (`agent/architect/`): Conducts research and creates implementation plans
3. **Developer Agent** (`agent/developer/`): Executes implementation plans and modifies code

Key architectural patterns:
- **State Management**: Uses Pydantic models with TypedDict for type-safe state
- **Tool Integration**: Search, codemap, and write tools follow LangChain patterns
- **Prompt Templates**: Markdown files in `prompts/` directories loaded dynamically
- **Atomic Tasks**: All changes are broken into smallest possible units

## Development Guidelines

1. **Adding New Tools**: Inherit from `BaseTool` and follow the pattern in `agent/tools/`
2. **Modifying Prompts**: Edit markdown files in `agent/*/prompts/` directories
3. **State Changes**: Update Pydantic models in `state.py` files
4. **Graph Modifications**: Update graph definitions in respective `graph.py` files

## Key Dependencies

- **LangGraph/LangChain**: Agent orchestration framework
- **Google Gemini**: Default LLM (Gemini 2.5 Pro)
- **langchain-google-genai**: Gemini support
- **tree-sitter**: Code parsing for codemap functionality
- **diff-match-patch**: Creating code diffs

## Important Notes

- The agent operates in a `workspace_repo` directory to isolate changes
- All file paths in tools are converted to absolute paths
- The system currently lacks test coverage
- Message history is maintained for debugging and resumability
import os
import sys
import operator
from dotenv import load_dotenv
from typing import Annotated, Literal, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

# 1. Load environment variables
load_dotenv()

# Fix for Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 2. Design the "Senses" (Tools)
@tool
def multiply(a: int, b: int) -> int:
    """
    Это твое 'Чувство Умножения'. 
    Используй этот инструмент ТОЛЬКО когда тебе нужно найти результат умножения двух чисел.
    """
    return a * b

tools = [multiply]
tool_node = ToolNode(tools)

# 3. Setup LLM (OpenRouter)
api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    print("ERROR: OPENROUTER_API_KEY not found in .env")
    sys.exit(1)

model = ChatOpenAI(
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1",
    model="google/gemini-2.0-flash-001", # Быстрая и точная модель
).bind_tools(tools)

# 4. Define Graph State
class AgentState(TypedDict):
    # Используем Annotated с operator.add для накопления сообщений
    messages: Annotated[list[BaseMessage], operator.add]
    path: list[str]
    # Сохраняем аргументы для финального ответа
    args: dict

# 5. Define Nodes
def call_model(state: AgentState):
    print("--- CALLING MODEL ---")
    response = model.invoke(state['messages'])
    
    # Извлекаем аргументы, если есть вызов инструмента
    args = {}
    if response.tool_calls:
        args = response.tool_calls[0]['args']
        
    return {
        "messages": [response],
        "args": args,
        "path": state.get("path", []) + ["agent"]
    }

def should_continue(state: AgentState) -> Literal["tools", "final_answer"]:
    last_message = state['messages'][-1]
    if last_message.tool_calls:
        print("--- DECISION: CALL TOOL ---")
        return "tools"
    return "final_answer"

def run_tools(state: AgentState):
    print("--- RUNNING TOOLS ---")
    result = tool_node.invoke(state)
    return {
        "messages": result["messages"],
        "path": state.get("path", []) + ["tools"]
    }

def final_answer_node(state: AgentState):
    """
    Финальный узел: программно формирует ответ, исключая галлюцинации LLM.
    """
    print("--- FINALIZING ---")
    
    if state.get("args"):
        a, b = state['args']['a'], state['args']['b']
        result = a * b
        response_text = f"Результат умножения {a} на {b} равен {result}."
        response = AIMessage(content=response_text)
    else:
        response = state['messages'][-1]
        
    return {
        "messages": [response],
        "path": state.get("path", []) + ["final_answer"]
    }

# 6. Build Graph
workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", run_tools)
workflow.add_node("final_answer", final_answer_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)

# ПРЯМАЯ СВЯЗЬ: Инструменты -> Финальный Ответ (минуя повторный вызов LLM)
workflow.add_edge("tools", "final_answer")
workflow.add_edge("final_answer", END)

app = workflow.compile()

# 7. Execute
if __name__ == "__main__":
    print("\n=== Smart Calculator (LangGraph + OpenRouter) ===")
    print("Type your math question or 'exit' to quit.\n")
    
    while True:
        user_input = input("You: ").strip()
        
        if user_input.lower() in ["exit", "quit", "выход"]:
            print("Goodbye!")
            break
            
        if not user_input:
            continue
            
        inputs = {
            "messages": [HumanMessage(content=user_input)],
            "path": []
        }
        
        print("\nAgent is thinking...")
        final_state = app.invoke(inputs)
        
        print(f"Agent: {final_state['messages'][-1].content}")
        print(f"[Execution Path: {' -> '.join(final_state['path'])}]\n")

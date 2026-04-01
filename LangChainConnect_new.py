import os
import threading
import yaml
from typing import Any, Dict, List

from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType, Tool
from langchain.memory import ConversationBufferMemory

from LLMAgent.simple_modeling.toolfour import Evaluation, BuildSimpleRoadNetwork
from LLMAgent.image_recognition.image_recognition_tool import image_recognition
from LLMAgent.road_extraction.satellite_predict_tool import satellite_pic_road_extraction
from LLMAgent.OSM.OSM_Tools import generatearoadnetworkmap


_AGENT = None
_AGENT_LOCK = threading.Lock()


def _load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def _build_agent():
    cfg = _load_config()
    os.environ["OPENAI_API_TYPE"] = cfg["OPENAI_API_TYPE"]
    os.environ["OPENAI_API_VERSION"] = cfg["OPENAI_API_VERSION"]
    os.environ["AZURE_OPENAI_ENDPOINT"] = cfg["OPENAI_API_BASE"]
    os.environ["OPENAI_API_KEY"] = cfg["OPENAI_API_KEY"]

    llm = ChatOpenAI(
        model=cfg.get("MODEL_NAME", "glm-4.6"),
        openai_api_key=cfg["OPENAI_API_KEY"],
        openai_api_base=cfg["OPENAI_API_BASE"],
        max_tokens=1024,
    )

    memory = ConversationBufferMemory(
        input_key="input",
        output_key="output",
    )

    tool_models = [
        #Evaluation(),        //此“交通状态评估（基于车辆数量）”功能不完善，先注释掉
        BuildSimpleRoadNetwork(), 
        image_recognition(""),
        satellite_pic_road_extraction(""),
        generatearoadnetworkmap(),
    ]

    tools = []
    for ins in tool_models:
        func = getattr(ins, "inference")
        tools.append(
            Tool(
                name=func.name,
                description=func.description,
                func=func,
                return_direct=True,
            )
        )

    return initialize_agent(
        tools,
        llm,
        agent=AgentType.CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        memory=memory,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        agent_kwargs={
            "ai_fix": "You are an AI expert to assist human with making traffic and transportation decisions."
        },
    )


def _short_text(text: Any, limit: int = 160) -> str:
    return str(text or "").replace("\r", " ").replace("\n", " ").strip()


def _summarize_intermediate_steps(intermediate_steps: Any) -> List[Dict[str, str]]:
    if not isinstance(intermediate_steps, list):
        return []

    summaries: List[Dict[str, str]] = []
    for step in intermediate_steps[:12]:
        if not isinstance(step, (tuple, list)) or len(step) < 2:
            continue

        action = step[0]
        observation = step[1]
        tool_name = getattr(action, "tool", "unknown")
        tool_input = getattr(action, "tool_input", "")

        summaries.append(
            {
                "tool": _short_text(tool_name, 80),
                "input": _short_text(tool_input, 120),
                "observation": _short_text(observation, 180),
            }
        )
    return summaries


def get_agent():
    global _AGENT
    with _AGENT_LOCK:
        if _AGENT is None:
            _AGENT = _build_agent()
        return _AGENT


def run_agent_query(user_prompt: str) -> Dict[str, Any]:
    if not user_prompt or not user_prompt.strip():
        raise ValueError("user_prompt 不能为空")

    agent = get_agent()
    with _AGENT_LOCK:
        raw = agent.invoke({"input": user_prompt.strip()})

    if isinstance(raw, dict):
        return {
            "output": str(raw.get("output", "")),
            "tool_steps": _summarize_intermediate_steps(raw.get("intermediate_steps", [])),
        }

    return {
        "output": str(raw),
        "tool_steps": [],
    }


if __name__ == "__main__":
    demo_prompt = "请为我生成以天安门为中心，半径500m内的路网地图。"
    print(run_agent_query(demo_prompt))

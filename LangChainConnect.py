import os
import yaml



# langchain不能高于0.2.0，否则initialize_agent方法被弃用
from langchain_openai import ChatOpenAI
from langchain_community.callbacks import get_openai_callback
from langchain.agents import initialize_agent, AgentType, Tool
from langchain.memory import ConversationBufferMemory


# 分别插入简单建模、图象识别、道路识别、OSM建模的类
from LLMAgent.simple_modeling.toolfour import Evaluation, BuildSimpleRoadNetwork
from LLMAgent.image_recognition.image_recognition_tool import image_recognition
from LLMAgent.road_extraction.satellite_predict_tool import (
    satellite_pic_road_extraction,
)
from LLMAgent.OSM.OSM_Tools import generatearoadnetworkmap




# STEP 1 配置大语言模型，可以替换为任意LLM，当前使用的是ChatGPT的API
# 后续我改成了国内的质谱AI
OPENAI_CONFIG = yaml.load(open("config.yaml"), Loader=yaml.FullLoader)
os.environ["OPENAI_API_TYPE"] = OPENAI_CONFIG["OPENAI_API_TYPE"]
os.environ["OPENAI_API_VERSION"] = OPENAI_CONFIG["OPENAI_API_VERSION"]
os.environ["AZURE_OPENAI_ENDPOINT"] = OPENAI_CONFIG["OPENAI_API_BASE"]
os.environ["OPENAI_API_KEY"] = OPENAI_CONFIG["OPENAI_API_KEY"]


llm = ChatOpenAI(
    model=OPENAI_CONFIG.get("MODEL_NAME", "glm-4.6"), # 优先读取配置，读不到则用默认值
    openai_api_key=OPENAI_CONFIG["OPENAI_API_KEY"],
    openai_api_base=OPENAI_CONFIG["OPENAI_API_BASE"],  # 国内直连地址
    max_tokens=1024
)

memory = ConversationBufferMemory()


# STEP 2 催眠大语言模型，让他可以按照一些特定的规则运行
prefix = """
You are a AI expert to assist human with making traffic and transportation decisions.
"""

# STEP 3 加载工具包，赋能大模型运行交通仿真
toolModels = [
    Evaluation(),   #车流评估   
    BuildSimpleRoadNetwork(),  #简单路网建模
    image_recognition(""),  #图像识别
    satellite_pic_road_extraction(""),  #卫星图道路识别
    generatearoadnetworkmap(), #OSM 路网生成
]
tools = []
for ins in toolModels:
    func = getattr(ins, "inference")
    tools.append(Tool(name=func.name, description=func.description, func=func,return_direct=True))
    #return_direct=True表示直接返回工具的输出结果，而不是让模型生成一个文本回复来描述工具的输出结果。这对于一些需要直接获取工具结果的场景非常有用，可以避免模型生成不必要的文本回复，提高效率和准确性。
    #此字段用来修复生成简单路网时模型重复调用工具生成路网的bug

# STEP 4 初始化TrafficGPT
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    memory=memory,
    #max_iterations=1,          # 仅允许1次迭代（避免生成路网时重复）  （指标不治本的方法，后续再看看能不能修复）
    #early_stopping_method="generate",  #一旦模型生成了看起来像“最终回答/结束状态”的文本（比如 Final Answer:），就尽快停止后续步骤。
    handle_parsing_errors=True,  
    agent_kwargs={"ai_fix": prefix}, 
)

# STEP 5 运行测试


with get_openai_callback() as cb:
        # agent.run(
        #     "帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./Database/LSRV/Shanghai_img.jpg'。"
        # )   此代码内存不够无法woc识别，精度太高
        # agent.run(
        #     "帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./resources/raw_data/11728825_15.tiff'。"
        # )
        #agent.run("请为我生成一张形状为 5,4 的规则路网地图。")
        agent.run("请为我生成以天安门为中心，半径500m内的路网地图。")
        print(cb)


# def main():
#     try:
#         with get_openai_callback() as cb:
#             # agent.run("...")
#             # agent.run(
#             #     "帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./Database/LSRV/Shanghai_img.jpg'。"
#             # )   此代码内存不够无法woc识别，精度太高
#             # agent.run(
#             #     "帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./resources/raw_data/11728825_15.tiff'。"
#             # )
#             # agent.run("请为我生成一张形状为 5,4 的规则路网地图。")
#             print("before run")
#             agent.run("请为我生成以内蒙古大学南校区为中心，半径500m内的路网地图。")
#             print("after run")
#     except Exception as e:
#         print("执行出错：", e)
#     finally:
#         print("in finally")
#         print("threads:", [t.name for t in threading.enumerate()])
#         print(cb)
#         print("before os._exit")


# if __name__ == "__main__":
#     main()


#        "帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./resources/satellite_img_3.tiff'。"
# agent.run("请为我生成一张形状为 5,4 的规则路网地图。")
# agent.run("Please generate a regular road network map with a shape of 5,4 for me.")
# agent.run("画一张4行5列的矩形路网。")
# agent.run("Draw a rectangular road network with 4 rows and 5 columns.")
# agent.run("矩形路网 3行5列")
# agent.run("rectangular network, 3 rows 5 columns.")

# agent.run("请为我生成以天安门为中心，半径1000m内的路网地图。")/("帮我生成一个颐和园附近2000m的路网图。")
# agent.run("Please generate a road network map centered around Tiananmen Square for me, "
#               "with a radius of 1000 meters.")
# agent.run("生成天安门附近1000米内的路网。")
# agent.run("Generate a road network within 1000 meters near Tiananmen Square.")
# agent.run("天安门, 500米")
# agent.run("Tiananmen Square, 500 meters")

# agent.run("帮助我识别卫星图像中的道路，并将生成的压缩文件的路径返回给我。卫星图像的路径是'./resources/satellite_img_3.tiff'。")
# agent.run("Help me identify the roads in a satellite image and return the path of the generated zip file to me. "
#               "Path to the satellite image is './resources/satellite_img_3.tiff'.")
# agent.run("Extract roads from a satellite image, "
#               "path to the image is './resources/satellite_img_3.tiff'.")
# agent.run("Extract roads, satellite image, './resources/satellite_img_3.tiff'")

# Help me identify the information of hand drawn image and return the path of the generated zip file to me. Path to the hand drawn image is './resources/hand_drawn_1.jpg'.

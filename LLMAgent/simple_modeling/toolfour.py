import csv
import time
import re
import pandas as pd

from LLMAgent.network_geojson import write_network_geojson
from LLMAgent.simple_modeling.build_simple_road_network import build_simple_road_network
from LLMAgent.simple_modeling.save_to_csv import save_nodes_to_csv,save_edges_to_csv
from LLMAgent.simple_modeling.visualize_road_network import visualize_road_network
from LLMAgent.simple_modeling.create_data_folder import create_data_folder

def prompts(name, description):
    def decorator(func):
        func.name = name
        func.description = description
        return func

    return decorator


class vehiclesCounter:
    def __init__(self, csvFile: str) -> None:
        self.csvFile = csvFile

    @prompts(name='Vehicle Number Counter',
             description="""
             Calculate the number of vehicles from start hour to end hour. 
             The input should be a comma seperated string, representing the start hour and the end hour, which should be integers between 0 and 24. 
             The output is the vehicle numbers during this time preiod.
             """)
    def inference(self, inputs: str) -> str:
        start, end = inputs.replace(' ', '').split(',')
        a, b = int(start), int(end)
        df = pd.read_csv(self.csvFile)
        df['time'] = pd.to_datetime(df['time'], format='%H:%M:%S')
        df['hour'] = pd.to_datetime(df['time'], format='%H:%M:%S').dt.hour
        data = df[(df["hour"] >= a) & (df["hour"] < b)]

        return len(data['carid'].unique())


class Evaluation:
    def __init__(self) -> None:
        pass

    @prompts(name="Evaluation",
             description="""
             Evaluation of traffic operation status of a intersection based on vehicle numbers. 
             The input must include an evaluation keyword and a number.
             Examples: "评估,40" or "traffic status 40"
             """)
    def inference(self, flow: str) -> str:
        text = str(flow or "").strip()
        if not re.search(r"评估|评价|traffic|status|拥堵|车流", text, flags=re.IGNORECASE):
            return "输入格式错误：请使用“评估,数字”，例如：评估,40"

        num_match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not num_match:
            return "输入格式错误：未识别到数字，请使用“评估,40”"

        try:
            value = float(num_match.group(0))
        except ValueError:
            return "输入格式错误：数字解析失败，请使用“评估,40”"

        if value < 70:
            return "Normal Operation Status"
        else:
            return "Heavy Traffic Status"


class BuildSimpleRoadNetwork:
    def __init__(self) -> None:
        pass

    @prompts(name='帮我生成一个简单路网',
             description="""
                    基于默认坐标生成一个N*M,精度为a的路网图
                    输入应当包括路网的长、宽、精度，用逗号间隔
                    长和宽必须输入，精度可以不输入，默认精度为445米
                    坐标默认为：center_lat=39.125, center_lon=161.567
                    比例尺默认为0.004（默认精度为445米）
                    比如:3,4，500或者3,4
                     """)
    def inference(self, flow: str) -> str:
        print("Original flow:", flow)
        processed_flow = flow.replace(' ', '').split(',')
        print("Processed flow:", processed_flow)
        if len(processed_flow) == 2:  # 如果只有两个值
            n, m = processed_flow
            a = ''  # 设置a为一个空字符串
        elif len(processed_flow) == 3:  # 如果有三个值
            n, m, a = processed_flow
        else:  # 如果值的数量不是2或3，则输入格式不正确
            return "输入格式错误：需要提供两个或三个参数，用逗号分隔"

        road_network = build_simple_road_network(n, m)
        if a != '':
            scale = round(float(a)/111323 , 5)
        else:
            scale = 0.004

        #def inference(self,flow: str) -> str:
        #n,m,a = flow.replace(' ', ' ').split(',')
        #road_network = build_simple_road_network(n,m)
        #if a != '':  # 检查a是否为非空字符串
            #scale = round(111323 / float(a), 5)  # 将a转换为浮点数类型并计算比例尺
        #else:
            #scale = 0.004

            # ====================== 核心修改 ======================
        import os
        import uuid
        from datetime import datetime
  
        # 用当前日期时间做文件夹名
        now = datetime.now()
        time_str = now.strftime("%Y%m%d_%H%M%S")  # 形如 20260328_154235
        task_suffix = uuid.uuid4().hex[:3]
        precision_value = float(a) if a != '' else 445.0
        if precision_value.is_integer():
            precision_tag = f"p{int(precision_value)}m"
        else:
            precision_tag = f"p{str(precision_value).replace('.', '_')}m"
        file_tag = f"{precision_tag}_{time_str}_{task_suffix}"

        folder_name = f"road_network_{file_tag}"
        base_folder = os.path.join("result", "simple_network")
        save_folder = os.path.join(base_folder, folder_name)
        os.makedirs(save_folder, exist_ok=True)

        # 文件也用同一时间命名
        node_csv_filename = os.path.join(save_folder, f'nodes_{file_tag}.csv')
        edge_csv_filename = os.path.join(save_folder, f'edges_{file_tag}.csv')
        image_output_path = os.path.join(save_folder, f'road_network_{file_tag}.png')
        geojson_output_path = os.path.join(save_folder, f'road_network_{file_tag}.geojson')

        # timestamp = int(time.time())
        # create_data_folder('data')
        # node_csv_filename = f'data\\nodes_{timestamp}.csv'
        # edge_csv_filename = f'data\\edges_{timestamp}.csv'
        # image_output_path = f'data\\road_network_{timestamp}.png'

        save_nodes_to_csv(road_network['nodes'], node_csv_filename)
        save_edges_to_csv(road_network['edges'], edge_csv_filename)
        visualize_road_network(road_network['nodes'], road_network['edges'], image_output_path)
        write_network_geojson(geojson_output_path, node_csv_filename, edge_csv_filename)

        result_string = f"已完成{n}*{m}简单路网绘制\n比例尺为{scale}\n节点文件保存在{node_csv_filename}的地址\n道路文件保存在{edge_csv_filename}的地址\nGeoJSON文件保存在{geojson_output_path}的地址\n路网预览图保存在{image_output_path}的地址。"
        return result_string
        
# 实例化 BuildSimpleRoadNetwork 类
#road_network_builder = BuildSimpleRoadNetwork()

#获取用户输入
#print("请输入路网的长、宽、精度（不输入默认精度为445米），用逗号隔开：")
#n, m ,a = input().split()

# 调用 inference 方法
#result = road_network_builder.inference(n, m)
#print(result)
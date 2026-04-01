import osm2gmns as og
import requests
import urllib
import json
import os
import uuid
import re
import math
from xpinyin import Pinyin
import time
import osmnx as ox
import matplotlib.pyplot as plt
from LLMAgent.OSM.create_data_folder import create_data_folder
from LLMAgent.network_geojson import write_network_geojson

TIANDITU_GEOCODE_KEY = "ab9109f928cefd3bfe7cc2f60fe50786"

class RoadNetworkGenerator:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _out_of_china(lat, lon):
        return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271

    @staticmethod
    def _transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    @staticmethod
    def _transform_lon(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    @staticmethod
    def gcj02_to_wgs84(lat, lon):
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return lat, lon
        if RoadNetworkGenerator._out_of_china(lat, lon):
            return lat, lon

        a = 6378245.0
        ee = 0.00669342162296594323
        d_lat = RoadNetworkGenerator._transform_lat(lon - 105.0, lat - 35.0)
        d_lon = RoadNetworkGenerator._transform_lon(lon - 105.0, lat - 35.0)
        rad_lat = lat / 180.0 * math.pi
        magic = math.sin(rad_lat)
        magic = 1 - ee * magic * magic
        sqrt_magic = math.sqrt(magic)
        d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
        d_lon = (d_lon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
        mg_lat = lat + d_lat
        mg_lon = lon + d_lon
        return lat * 2 - mg_lat, lon * 2 - mg_lon

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        earth_radius_m = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return earth_radius_m * c

    @staticmethod
    def _clip_graph_to_radius(G, center_lat, center_lon, radius_m):
        keep_nodes = []
        for node_id, data in G.nodes(data=True):
            node_lat = data.get('y')
            node_lon = data.get('x')
            if node_lat is None or node_lon is None:
                continue
            if RoadNetworkGenerator._haversine_m(center_lat, center_lon, node_lat, node_lon) <= radius_m:
                keep_nodes.append(node_id)

        if not keep_nodes:
            return G

        clipped = G.subgraph(keep_nodes).copy()
        if len(clipped.nodes) == 0:
            return G
        return clipped

    @staticmethod
    def get_road_network(lat, lon, radius):
        G = ox.graph_from_point((lat, lon), dist=radius, network_type='all_private', simplify=False)
        return G

    @staticmethod
    def output_net_to_csv(net, csv_output_folder):  #csv_file->csv_output_folder
        og.consolidateComplexIntersections(net, auto_identify=True)
        og.outputNetToCSV(net, output_folder=csv_output_folder)

    @staticmethod
    def _sanitize_path_tag(raw: str, fallback: str = "location") -> str:
        text = (raw or "").strip().lower()
        text = re.sub(r"[^a-z0-9_-]", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text or fallback

    @staticmethod
    def get_geocode(addr):
        key = "207c2bc139db282279c57c987b841b18"
        base_url = "https://restapi.amap.com/v3/geocode/geo?"
        params = {
            "key": key,
            "address": addr,
            "city": addr,
            "output": "json",
        }

        # 天地图 geocode 实现保留在这里，便于后续继续实验或切回。
        # base_url = "https://api.tianditu.gov.cn/geocoder"
        # ds = json.dumps({"keyWord": addr}, ensure_ascii=False)
        # params = {
        #     "ds": ds,
        #     "tk": TIANDITU_GEOCODE_KEY,
        # }

        try:
            url = base_url + urllib.parse.urlencode(params)
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
                },
            )
            response = urllib.request.urlopen(req, timeout=20)
            content = response.read()
            jsonData = json.loads(content)

            print("高德返回:", jsonData)

            if jsonData.get("status") == "1" and jsonData.get("geocodes"):
                location = jsonData["geocodes"][0]["location"]
                lon, lat = location.split(",")
                return lon.strip(), lat.strip()

            return None, None

        except Exception as e:
            print("地址解析异常:", str(e))
            return None, None

    @staticmethod
    def generate_road_network_map(input):

        try:
            # 1. 解析输入（从最后一个逗号分割，防止地址带逗号报错）
            input_clean = input.replace(' ', '').strip()
            parts = input_clean.rsplit(',', 1)
            if len(parts) != 2:
                return "错误：输入格式应为 → 地址,半径（例如：北京市中关村,500）"
            addr, search_radius = parts
            radius = int(search_radius)
            if radius <= 0 or radius > 5000:
                return "错误：半径必须在 1~5000 米之间"
        except:
            return "错误：输入格式不正确"
    
        # 2. 解析地址经纬度
        longitude, latitude = RoadNetworkGenerator.get_geocode(addr)
        print(f"解析地址经纬度（高德 GCJ-02）：{addr} → 经度：{longitude}，纬度：{latitude}")
    
        if longitude is None or latitude is None:
            return "错误：无法解析地址经纬度"
    
        try:
            lon = float(longitude)
            lat = float(latitude)
        except:
            return "错误：经纬度格式无效"

        # 高德地理编码返回 GCJ-02；OSM/OSMnx 使用 WGS84。
        # 若不转换，中心点会在国内区域出现明显偏移。
        lat, lon = RoadNetworkGenerator.gcj02_to_wgs84(lat, lon)
        print(f"转换后 WGS84 中心点：{addr} → 经度：{lon}，纬度：{lat}")
    
        # 3. 文件路径配置
        create_data_folder(os.path.join('result', 'osm_network'))
        time_str = time.strftime("%Y%m%d_%H%M%S")
        task_suffix = uuid.uuid4().hex[:3]
        radius_tag = f"r{radius}m"
        file_tag = f"{radius_tag}_{time_str}_{task_suffix}"

        addr_pinyin_raw = Pinyin().get_pinyin(addr, '')
        addr_pinyin = RoadNetworkGenerator._sanitize_path_tag(addr_pinyin_raw, fallback="place")
        base_path = os.path.join('result', 'osm_network', f'{addr_pinyin}_{file_tag}')

        # 先创建输出文件夹 osm2gmns 1.0.1 版本需要
        create_data_folder(base_path)

        osm_file = os.path.join(base_path, f'{addr_pinyin}_{file_tag}.osm')
        img_file = os.path.join(base_path, f'{addr_pinyin}_{file_tag}.png')
        geojson_file = os.path.join(base_path, f'{addr_pinyin}_{file_tag}.geojson')
        csv_output_folder = base_path



    
        # ==================== 核心优化：只下载一次路网 ====================
        # 一次性获取 G 对象（osmnx 内部自动下载，国内更稳定）
        G = RoadNetworkGenerator.get_road_network(lat, lon, radius)
        G = RoadNetworkGenerator._clip_graph_to_radius(G, lat, lon, radius)
    
        # 直接从 G 导出 OSM 文件 → 不再需要重复下载！
        ox.save_graph_xml(G, filepath=osm_file)
        # =================================================================

        # 4. OSM → GMNS CSV
        try:
            net = og.getNetFromFile(osm_file)
            RoadNetworkGenerator.output_net_to_csv(net, csv_output_folder)
            write_network_geojson(
                geojson_file,
                os.path.join(csv_output_folder, 'node.csv'),
                os.path.join(csv_output_folder, 'link.csv'),
            )
        except Exception as e:
            return f"错误：OSM 转 GMNS 失败 → {str(e)}"
        
        # 5. 绘图
        try:
            fig, ax = plt.subplots(figsize=(8, 8), facecolor='white')
            ox.plot_graph(
                ox.project_graph(G),
                ax=ax,
                bgcolor='white',
                node_size=0,
                edge_color='black',
                show=False,    # 不弹窗
                close=True     # 自动关闭
            )
            fig.savefig(img_file, bbox_inches='tight', dpi=300)
            plt.close('all')  # 释放内存
        except Exception as e:
            return f"错误：绘图失败 → {str(e)}"
    
        # 6. 返回固定格式
        result = (f"Your final answer must be formatted as below without any change:"
                  f"GMNS file path: {csv_output_folder}\n"
                  f"GeoJSON file path: {geojson_file}\n"
                  f"Network image path: {img_file}\n"
                  f"Process finished.")
        

        return result
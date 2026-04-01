import osm2gmns as og
import requests
import urllib
import json
from xpinyin import Pinyin
import osmnx as ox
import time
#import multiprocessing


import matplotlib.pyplot as plt
from LLMAgent.OSM.create_data_folder import create_data_folder

# class RoadNetworkGenerator:
#     def __init__(self) -> None:
#         pass

#     @staticmethod
#     def get_road_network(lat, lon, radius):
#         one_mile = radius  # 米
#         G = ox.graph_from_point((lat, lon), dist=one_mile, network_type='all_private', simplify=False)
#         return G

#     @staticmethod
#     def output_net_to_csv(net, csv_file):
#         og.consolidateComplexIntersections(net, auto_identify=True)
#         og.outputNetToCSV(net, csv_file)

#     @staticmethod
#     def get_geocode(addr):
#         #key = '97267e642f34dc2df3c890f74c6b8205'
#         key = '207c2bc139db282279c57c987b841b18'
#         baseUrl = 'https://restapi.amap.com/v3/geocode/geo?'
#         params = {
#             'key': key,
#             'address': addr
#         }
#         url = baseUrl + urllib.parse.urlencode(params)
#         req = urllib.request.Request(url)
#         content = urllib.request.urlopen(req).read()
#         jsonData = json.loads(content)
#         lon, lat = '', ''
#         if jsonData['status'] == '1':
#             try:
#                 corr = jsonData['geocodes'][0]['location']
#                 lon, lat = corr.split(',')[0], corr.split(',')[1]
#             except:
#                 lon, lat = '0', '0'
#         else:
#             print('出错了')
#         return (lon, lat)

#     #连接国外OSM的api，目前已经换成osmnx国内可访问模式，即此函数不作用
#     @staticmethod
#     def get_road_network_data(lat, lon, radius, addr):

#         response = None

#         #overpass_url = "http://www.overpass-api.de/api/interpreter"  #国外接口（备用）
#         overpass_url = "https://overpass-api.de/api/interpreter"  # 国外接口（备用）
#         #overpass_url = "https://overpass.openstreetmap.cn/api/interpreter"  # 国内镜像（推荐）
#         #overpass_url ="https://overpass.kumi.systems/api/interpreter" # 国内镜像（推荐）



#         query = f'[out:xml][timeout:30];way(around:{radius},{lat},{lon})["highway"];(._;>;);out meta;'

#         # 设置请求头
#         headers = {
#             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 Edg/117.0.2045.60",
#             "Content-Type": "application/x-www-form-urlencoded"
#         }

#         # 如果你开启了科学上网工具，取消下面这段注释，并将端口改为你代理软件的端口 (例如 Clash 默认是 7890)
#         proxies = {
#              "http": "http://127.0.0.1:7899",
#              "https":"http://127.0.0.1:7899",
#         }

#         # # 发送 HTTP POST 请求
#         # response = requests.post(
#         #     overpass_url,
#         #     data=query.encode('utf-8'),
#         #     headers=headers,
#         #     timeout=20,
#         #     proxies=proxies,  # 核心：让Python走代理访问外网
#         # )
#         #
#         # # 将响应文本保存为 OSM 文件
#         # if response.status_code == 200:
#         #     with open(addr, "w", encoding="utf-8") as f:
#         #         f.write(response.text)

#         # 发送请求并增加完整的错误处理
#         try:
#             response = requests.post(
#                 overpass_url,
#                 data=query.encode('utf-8'),
#                 headers=headers,
#                 timeout=30,
#                 proxies=proxies,
#                 verify=False  # 必须加：跳过SSL证书错误
#             )

#             # 1. 状态码非200时显示错误
#             if response.status_code == 200:
#                 with open(addr, "w", encoding="utf-8") as f:
#                     f.write(response.text)
#                 print(f" OSM数据下载成功！已保存到：{addr}")
#             else:
#                 # 显示具体的状态码和错误信息
#                 error_msg = f" 下载失败！服务器返回非200状态码：{response.status_code}，响应内容：{response.text[:200]}"
#                 print(error_msg)
#                 raise Exception(error_msg)  # 抛出异常，让上层代码捕获

#         # 2. 捕获各类网络异常并显示错误
#         except requests.exceptions.Timeout:
#             error_msg = " 下载超时！服务器在20秒内未响应，请检查网络或增大timeout值"
#             print(error_msg)
#             raise Exception(error_msg)
#         except requests.exceptions.ProxyError:
#             error_msg = f" 代理连接失败！请检查代理端口{proxies['http']}是否正确，或代理软件是否开启"
#             print(error_msg)
#             raise Exception(error_msg)
#         except requests.exceptions.ConnectionError:
#             error_msg = " 网络连接失败！请检查外网是否可用，或Overpass API是否正常"
#             print(error_msg)
#             raise Exception(error_msg)
#         except Exception as e:
#             error_msg = f" 下载OSM数据时发生未知错误：{str(e)}"
#             print(error_msg)
#             raise Exception(error_msg)


# def _gmns_convert_worker(osm_file, csv_file, result_queue):
#     """独立子进程：专门跑 osm2gmns，跑完即销毁"""
#     try:
#         import osm2gmns as og
#         # 执行完整的转换逻辑
#         net = og.getNetFromFile(osm_file)
#         og.consolidateComplexIntersections(net, auto_identify=True)
#         og.outputNetToCSV(net, csv_file)
#         # 成功回传
#         result_queue.put(("success", None))
#     except Exception as e:
#         # 异常回传
#         result_queue.put(("error", str(e)))

class RoadNetworkGenerator:
    def __init__(self) -> None:
        pass

    @staticmethod
    def get_road_network(lat, lon, radius):
        G = ox.graph_from_point((lat, lon), dist=radius, network_type='all_private', simplify=False)
        return G

    @staticmethod
    def output_net_to_csv(net, csv_output_folder):  #csv_file->csv_output_folder
        og.consolidateComplexIntersections(net, auto_identify=True)
        og.outputNetToCSV(net, output_folder=csv_output_folder)
        #og.outputNetToCSV(net, csv_file)

    @staticmethod
    def get_geocode(addr):
        key = "207c2bc139db282279c57c987b841b18"
        baseUrl = "https://restapi.amap.com/v3/geocode/geo?"

        # 必加 city！不加必失败！
        params = {
            "key": key,
            "address": addr,
            "city": addr,        # 核心修复
            "output": "json"     # 明确格式
        }

        try:
            url = baseUrl + urllib.parse.urlencode(params)
            req = urllib.request.Request(url)
       
            response = urllib.request.urlopen(req)
            content = response.read()
            jsonData = json.loads(content)

            # 调试输出，看看高德返回了什么（你就能看到真实原因）
            print("高德返回:", jsonData)

            # 严格判断
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
        #return 'mocked_result'  # 先返回一个mock结果，后续再完善这个函数的实现

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
        print(f"解析地址经纬度：{addr} → 经度：{longitude}，纬度：{latitude}")
    
        if longitude is None or latitude is None:
            return "错误：无法解析地址经纬度"
    
        try:
            lon = float(longitude)
            lat = float(latitude)
        except:
            return "错误：经纬度格式无效"
    
        # 3. 文件路径配置
        create_data_folder('data')
        addr_pinyin = Pinyin().get_pinyin(addr, '')
        base_path = f'data/{addr_pinyin}'       
        osm_file = f'{base_path}.osm'

        csv_output_folder = base_path
        #csv_file = f'{base_path}.csv'
        img_file = f'{base_path}.png'

        # 先创建输出文件夹
        create_data_folder(csv_output_folder)


        #3.文件路径配置（有时间戳且保存到同一文件夹版本）        
        create_data_folder('data')
        time_str = time.strftime("%Y%m%d_%H%M%S")

        addr_pinyin = Pinyin().get_pinyin(addr, '')
        #base_path = f'data/{addr_pinyin}'       
        base_path = f'data/{addr_pinyin}_{time_str}'  # 这里加时间戳

        # 先创建输出文件夹 osm2gmns 1.0.1 版本需要
        create_data_folder(base_path)

        osm_file = f'{base_path}/{addr_pinyin}_{time_str}.osm'
        img_file = f'{base_path}/{addr_pinyin}_{time_str}.png'
        csv_output_folder = base_path

        #osm_file = f'{base_path}.osm'
        #img_file = f'{base_path}.png'


    
        # ==================== 核心优化：只下载一次路网 ====================
        # 一次性获取 G 对象（osmnx 内部自动下载，国内更稳定）
        G = RoadNetworkGenerator.get_road_network(lat, lon, radius)
    
        # 直接从 G 导出 OSM 文件 → 不再需要重复下载！
        ox.save_graph_xml(G, filepath=osm_file)
        # =================================================================

        # import os
        # if os.path.exists(osm_file):
        #     # 本地已有 OSM 文件 → 直接加载 G 对象，不重新下载
        #     print(f"本地已存在路网文件，直接加载：{osm_file}")
        #     G = ox.load_graphml(osm_file.replace(".osm", ".graphml"))  # 用 graphml 加载更快
        # else:
        #     # 本地无文件 → 下载路网，并保存到本地
        #     print(f"本地无路网文件，开始下载：{addr}")
        #     G = RoadNetworkGenerator.get_road_network(lat, lon, radius)

        #     # 保存 2 种格式：osm（通用） + graphml（osmnx专用，加载更快）
        #     ox.save_graph_xml(G, filepath=osm_file)
        #     ox.save_graphml(G, filepath=osm_file.replace(".osm", ".graphml"))
        # # ==================================================================
    
        # 4. OSM → GMNS CSV
        try:
            net = og.getNetFromFile(osm_file)
            #RoadNetworkGenerator.output_net_to_csv(net, csv_file)
            RoadNetworkGenerator.output_net_to_csv(net, csv_output_folder)            
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
                f"Network image path: {img_file}\n"
                f"Process finished.")
        

        return result

    # @staticmethod
    # def generate_road_network_map(input):

    #     #return 'mocked_result'  # 先返回一个mock结果，后续再完善这个函数的实现
    #     addr, search_radius = input.replace(' ', '').split(',')

    #     # 调用函数获取经纬度
    #     longitude, latitude = RoadNetworkGenerator.get_geocode(addr)
        
    #     print(f"解析地址经纬度：{addr} -> 经度：{longitude}，纬度：{latitude}")

    #     if longitude is None or latitude is None:
    #         return "错误：无法解析地址经纬度"

    #     # 修改存储路径(旧)
    #     # create_data_folder('data')
    #     # addr_pinyin = Pinyin().get_pinyin(addr, '')
    #     # csv_file = f'data/{addr_pinyin}'

    #     # 修改存储路径(新)
    #     create_data_folder('data')
    #     addr_pinyin = Pinyin().get_pinyin(addr, '')
    #     # 统一路径，只写一次
    #     base_path = f'data/{addr_pinyin}'
    #     osm_file = f'{base_path}.osm'
    #     csv_file = f'{base_path}.csv'
    #     img_file = f'{base_path}.png'

    #     # 调用函数获取路网数据
    #     #RoadNetworkGenerator.get_road_network_data(latitude, longitude, search_radius, f'data/{addr_pinyin}.osm')
    #     RoadNetworkGenerator.get_road_network_data(latitude, longitude, search_radius, osm_file)



    #     # 转换为 CSV 文件
    #     #net = og.getNetFromFile(f'data/{addr_pinyin}.osm')
    #     net = og.getNetFromFile(osm_file)       
    #     RoadNetworkGenerator.output_net_to_csv(net, csv_file)

    #     # 获取地图数据并可视化
    #     G = RoadNetworkGenerator.get_road_network(float(latitude), float(longitude), int(search_radius))

    #     # 修复绘图：不弹窗、不卡死、不泄漏
    #     #plt.ion()  # 关闭交互模式，避免弹窗 

    #     fig, ax = plt.subplots(figsize=(8, 8), facecolor='white')
    #     #ox.plot_graph(ox.project_graph(G), bgcolor='white', node_size=0,edge_color='black',ax=ax)

    #     ox.plot_graph(
    #         ox.project_graph(G),
    #         bgcolor='white',
    #         node_size=0,
    #         edge_color='black',
    #         ax=ax,
    #         show=True,
    #         close=False,
    #     )

    #     # 输出可视化结果
    #     #image_file = f'data/{addr_pinyin}.png'        
    #     fig.savefig(img_file, bbox_inches='tight', dpi=300)

    #     # plt.show(block=True)   # 等待你手动关闭图片
    #     # #plt.close(fig)

    #     return (f"Your final answer must be formatted as below without any change:"
    #             f"GMNS file path: {csv_file}\n"
    #             f"Network image path: {img_file}\n"
    #             f"Process finished.")





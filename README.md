# MixSimGPT

MixSimGPT 是一个面向交通与路网生成任务的智能体系统。项目使用 FastAPI 提供 Web 服务和交互页面，后端集成 LangChain Agent、OSM 路网抓取、简单路网建模、手绘图识别和卫星图道路提取等能力，用于辅助生成、识别、转换和下载交通路网相关成果。

## 功能特性

- 智能体对话：通过自然语言调用路网生成、图像识别、OSM 路网抓取等工具。
- 简单路网生成：根据行列数和精度参数生成规则路网，并输出 CSV、GeoJSON、预览图等结果。
- OSM 路网生成：根据地点名称和半径抓取 OpenStreetMap 路网，并转换为可下载成果。
- 手绘图识别：上传或指定本地手绘道路图像，识别并重建道路网络。
- 卫星图道路提取：对卫星遥感图像进行道路提取，生成路网结果。
- 任务队列与进度：前端可查看任务状态、阶段进度、日志、历史记录和下载产物。
- 结果下载：支持单个产物下载、图片预览和任务结果打包下载。

## 技术栈

- Python
- FastAPI / Uvicorn
- LangChain / langchain-openai
- OpenAI 兼容模型接口
- GeoPandas / OSMnx / osm2gmns / Shapely
- PyTorch / OpenCV / scikit-image
- 原生 HTML / CSS / JavaScript
- Leaflet 地图渲染

## 目录结构

```text
MixsimGPT-main/
|-- main.py                         # 根入口，启动 FastAPI 服务
|-- frontend/
|   |-- main.py                     # Web 服务、API、任务队列和文件下载逻辑
|   |-- templates/index.html        # 前端页面模板
|   |-- static/                     # 前端 JS、CSS、Leaflet 静态资源
|   |-- uploads/                    # 前端上传文件目录
|   `-- download_cache/             # 临时下载和打包缓存
|-- LLMAgent/
|   |-- simple_modeling/            # 简单路网生成工具
|   |-- OSM/                        # OSM 路网抓取与转换工具
|   |-- image_recognition/          # 手绘图识别工具
|   |-- road_extraction/            # 卫星图道路提取工具
|   `-- network_geojson.py          # 路网 GeoJSON 相关处理
|-- LangChainConnect_new.py         # LangChain Agent 初始化与工具注册
|-- config.yaml                     # 大模型接口配置
|-- requirements.txt                # Python 依赖
|-- data/                           # 示例或中间路网数据
|-- resources/                      # 模型、图片或其他资源文件
|-- result/                         # 任务输出结果
`-- uploads/                        # 根目录上传缓存
```

## 环境准备

建议使用 Python 3.9 到 3.11，并在虚拟环境中安装依赖。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

如果安装地理空间相关依赖时失败，优先检查本机是否具备 GDAL、Fiona、GeoPandas、PyProj 等包所需的二进制环境。Windows 环境下可以考虑使用 Conda 环境安装这些地理依赖后，再安装项目其他依赖。

## 模型配置

系统从根目录 `config.yaml` 读取大模型接口配置。主要字段如下：

```yaml
MODEL_NAME: "your-model-name"
OPENAI_API_TYPE: "openai-compatible-provider"
OPENAI_API_VERSION: "v4"
OPENAI_API_BASE: "https://your-api-base"
OPENAI_API_KEY: "your-api-key"
```

注意事项：

- `LangChainConnect_new.py` 会读取 `config.yaml` 并创建 `ChatOpenAI` 实例。
- `OPENAI_API_BASE` 需要填写兼容 OpenAI Chat Completions 的服务地址。
- 请勿将真实 API Key 提交到公开仓库。建议在协作或发布前改用本地配置、环境变量或示例配置文件。

## 启动系统

在项目根目录执行：

```powershell
python main.py
```

默认启动地址：

```text
http://127.0.0.1:8000/
```

也可以直接使用 Uvicorn 启动：

```powershell
python -m uvicorn frontend.main:app --host 127.0.0.1 --port 8000
```

如果需要局域网内其他设备访问，可将 host 改为 `0.0.0.0`：

```powershell
python -m uvicorn frontend.main:app --host 0.0.0.0 --port 8000
```

## 使用方式

打开首页后，可以通过页面中的表单或对话框提交任务：

- 输入自然语言，让 Agent 自动判断应调用的工具。
- 生成简单路网时，填写行数、列数和可选精度。
- 生成 OSM 路网时，填写地点名称和搜索半径。
- 处理手绘图或卫星图时，可以上传图片，也可以填写本地图片路径。
- 任务提交后，可在任务列表中查看进度、日志、产物预览和下载按钮。

## API 概览

主要接口由 `frontend/main.py` 提供：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | Web 首页 |
| `GET` | `/api/session` | 获取当前服务会话 ID |
| `POST` | `/api/chat` | 提交 Agent 对话任务 |
| `POST` | `/api/tasks/simple-network` | 创建简单路网生成任务 |
| `POST` | `/api/tasks/osm-network` | 创建 OSM 路网生成任务 |
| `POST` | `/api/tasks/handdrawn` | 创建手绘图识别任务 |
| `POST` | `/api/tasks/satellite` | 创建卫星图道路提取任务 |
| `GET` | `/api/tasks` | 获取任务列表 |
| `GET` | `/api/tasks/{task_id}` | 获取单个任务状态 |
| `GET` | `/api/tasks/{task_id}/events` | 订阅任务进度事件 |
| `GET` | `/api/tasks/{task_id}/logs` | 获取任务日志 |
| `POST` | `/api/tasks/{task_id}/cancel` | 取消任务 |
| `POST` | `/api/tasks/{task_id}/delete` | 删除已结束任务记录 |
| `GET` | `/api/tasks/{task_id}/download-all` | 打包下载任务产物 |
| `GET` | `/api/artifacts/{artifact_id}/download` | 下载单个产物 |
| `GET` | `/api/artifacts/{artifact_id}/view` | 预览图片产物 |

## 输出结果

不同任务会在 `result/`、`data/`、`frontend/download_cache/` 等目录下生成文件。常见产物包括：

- `node.csv` / `link.csv`
- `nodes_*.csv` / `edges_*.csv`
- `road_network.geojson`
- `road_network_*.png`
- `gmns.zip`
- 道路提取中间图和最终结果图

前端会自动识别任务结果中的常见文件，并注册为可下载产物。

## 开发说明

- 根入口 `main.py` 导入 `frontend.main:app`，适合直接运行整个系统。
- `frontend/main.py` 负责 Web API、上传文件、任务队列、进度日志、结果注册和下载。
- `LangChainConnect_new.py` 注册 Agent 可调用的工具，包括简单路网生成、图像识别、卫星图道路提取和 OSM 路网生成。
- 算法能力主要位于 `LLMAgent/`，前端不会直接修改算法代码。
- 部分中文字符串在当前代码中可能存在编码显示异常，但不影响 README 的 UTF-8 编写。

## 常见问题

### 1. 启动后无法调用 Agent

检查 `config.yaml` 中模型名称、API Base 和 API Key 是否正确，并确认网络可以访问对应模型服务。

### 2. 地图或 OSM 任务失败

OSM 相关功能依赖网络、地理编码和 OSM 数据服务。请确认地点名称可被解析，并适当减小半径后重试。

### 3. 卫星图道路提取较慢

该功能依赖图像处理和深度学习模型，运行时间与图片尺寸、硬件性能和模型资源有关。建议先使用较小图片验证流程。

### 4. 上传图片失败

默认允许的图片格式包括 `png`、`jpg`、`jpeg`、`bmp`、`webp`、`tif`、`tiff`，单个上传文件最大约 10 MB。

## 许可证

当前仓库未发现明确许可证文件。如需开源发布，请补充 `LICENSE` 并确认第三方模型、数据和依赖的使用许可。

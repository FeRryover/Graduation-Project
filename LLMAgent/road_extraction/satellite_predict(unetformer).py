import os
import shutil
import uuid
import warnings
import cv2
import torch
import numpy as np
import torchvision.transforms as T
from datetime import datetime
import zipfile

# 导入你自定义的工具模块
from LLMAgent.road_extraction.UNetFormer import UNetFormer 
from LLMAgent.road_extraction.Canny import byjc
from LLMAgent.road_extraction.Resize import resize_image
from LLMAgent.road_extraction.CornerDetection import jdjc
from LLMAgent.road_extraction.Draw import draw
from LLMAgent.network_geojson import write_network_geojson

warnings.filterwarnings("ignore")

def predict_road_from_satellite_image(pic_path):
    # 1. 环境与路径准备
    current_time = datetime.now()
    folder_name = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    work_dir = os.path.dirname(pic_path)
    work_folder = os.path.join(work_dir, folder_name)
    os.makedirs(work_folder, exist_ok=True)
    shutil.copy(pic_path, os.path.join(work_folder, os.path.basename(pic_path)))

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    
    feature_root = os.path.join('result', 'satellite')
    time_tag = current_time.strftime("%Y%m%d_%H%M%S")
    task_suffix = uuid.uuid4().hex[:3]
    output_root = os.path.join(feature_root, f'task_{time_tag}_{task_suffix}')
    
    os.makedirs(os.path.join(output_root, 'gmns'), exist_ok=True)
    os.makedirs(os.path.join(output_root, 'temp', 'success'), exist_ok=True)

    # 2. 模型初始化
    # 注意：num_classes 必须与微调训练时一致（2分类任务设为1）
    model = UNetFormer(num_classes=1)
    model_path = "resources/UNetFormer_best_custom.pth"
    
    if os.path.exists(model_path):
        # 使用 map_location 确保从 4090 环境下载的权重能在本地 3060 顺利加载
        model.load_state_dict(torch.load(model_path, map_location=DEVICE))
        model.to(DEVICE)
        model.eval()
        print(f"--- 成功加载 2022 UNetFormer 视觉基座 (Device: {DEVICE}) ---")
    else:
        raise FileNotFoundError(f"错误：在 resources 文件夹下未找到权重文件 {model_path}")

    # 3. 图像读取与预处理
    image_bgr = cv2.imread(pic_path)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h_orig, w_orig = image_bgr.shape[:2]

    # 标准化参数（必须与训练脚本 train.py 一致）
    transform = T.Compose([
        T.ToPILImage(),
        T.Resize((512, 512)), # UNetFormer 建议固定输入尺寸
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    input_tensor = transform(image_rgb).unsqueeze(0).to(DEVICE)

    # 4. 模型推理
    print("正在进行路网语义分割...")
    with torch.no_grad():
        output = model(input_tensor)
        # 过 Sigmoid 激活函数获取概率图
        prob = torch.sigmoid(output)
        # 二值化处理：概率大于 0.5 判定为道路 (255)，否则为背景 (0)
        pred_mask = (prob > 0.5).cpu().numpy().astype(np.uint8) * 255
        pred_mask = pred_mask[0][0] # 提取出 (512, 512) 矩阵

    # 5. 结果后处理
    # 将 512x512 的预测结果还原回原始卫星图尺寸
    binary_pred_mask = cv2.resize(pred_mask, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)

    # 生成“白底黑路”图以适配后续角点检测逻辑
    # binary_pred_mask 是单通道，需要转为 BGR 后进行反转
    binary_pred_bgr = cv2.cvtColor(binary_pred_mask, cv2.COLOR_GRAY2BGR)
    inverted_image = 255 - binary_pred_bgr
    
    save_path_bin = os.path.join(work_folder, "unetformer_binary_output.png")
    cv2.imwrite(save_path_bin, inverted_image)
    print(f"视觉提取完成，结果保存至: {save_path_bin}")

    # 6. 后续逻辑：角点检测与拓扑生成
    print("启动智能体工具链：角点检测与路网拓扑识别...")
    
    # 灰度化处理
    gray_image = cv2.cvtColor(inverted_image, cv2.COLOR_BGR2GRAY)
    line_width = 3  # 优化距离，建议取线宽一半

    # 角点检测相关参数
    maxCorners, qualityLevel, minDistance = 1000, 0.01, 30
    blockSize, useHarrisDetector, k = 30, False, 0.02

    gray_img_path = os.path.join(output_root, 'gray_image.jpg')
    temp_save_path = os.path.join(output_root, 'temp_result.jpg')
    jdjc_result_path = os.path.join(output_root, 'jdjc_result.jpg')
    best_result_path = os.path.join(output_root, 'best_result.jpg')

    # 保存灰度图供后续函数调用
    cv2.imwrite(gray_img_path, gray_image)

    # 工具链：Resize -> 边缘优化 -> 角点检测
    resized_gray = resize_image(gray_img_path)
    binary_canny = byjc(resized_gray, temp_save_path)
    
    # 获取优化后的角点坐标列表
    best_xy_list = jdjc(binary_canny, jdjc_result_path, line_width, 
                        maxCorners, qualityLevel, minDistance, 
                        blockSize, useHarrisDetector, k)

    # 绘图并生成 link.csv (拓扑连通逻辑)
    # target 参数决定了允许搜索连接的最大距离平方
    draw(best_xy_list, temp_save_path, best_result_path, min_mse=20, target=160000, output_root=output_root)

    # 生成最终的 GeoJSON 文件
    geojson_path = os.path.join(output_root, 'road_network.geojson')
    write_network_geojson(
        geojson_path,
        os.path.join(output_root, 'gmns', 'corners.csv'),
        os.path.join(output_root, 'gmns', 'link.csv'),
    )

    # 打包 GMNS 数据集
    zip_file_path = os.path.join(output_root, 'gmns.zip')
    with zipfile.ZipFile(zip_file_path, 'w') as zipf:
        zipf.write(os.path.join(output_root, 'gmns', 'corners.csv'), 'gmns/corners.csv')
        zipf.write(os.path.join(output_root, 'gmns', 'link.csv'), 'gmns/link.csv')

    print(f"--- 任务成功完成！GeoJSON 已生成 ---")
    return zip_file_path, best_result_path, geojson_path
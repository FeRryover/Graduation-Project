from LLMAgent.road_extraction.Canny import byjc
from LLMAgent.road_extraction.Resize import resize_image
from LLMAgent.road_extraction.CornerDetection import jdjc
from LLMAgent.road_extraction.Draw import draw
from LLMAgent.network_geojson import write_network_geojson
from torch.utils.data import DataLoader
from datetime import datetime
import cv2
import os
import shutil
import uuid
import warnings
import albumentations as album
import matplotlib.pyplot as plt
import numpy as np
import segmentation_models_pytorch as smp
import torch
import zipfile
import time

warnings.filterwarnings("ignore")

_MODEL_CACHE = {}


def _get_cached_model(model_path, device):
    cache_key = (os.path.abspath(model_path), str(device))
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"未找到模型: {model_path}")

    model = torch.load(model_path, map_location=device)
    model.eval()
    _MODEL_CACHE[cache_key] = model
    return model


def predict_road_from_satellite_image(pic_path, debug_visualization=False):
    total_start = time.perf_counter()
    stage_cost = {}

    def mark(stage_name, start_ts):
        stage_cost[stage_name] = round(time.perf_counter() - start_ts, 4)

    t0 = time.perf_counter()
    current_time = datetime.now()
    folder_name = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    work_dir = os.path.dirname(pic_path)  # 获取图片所在目录
    work_folder = os.path.join(work_dir, folder_name)  # 创建work文件夹的路径
    os.makedirs(work_folder, exist_ok=True)
    shutil.copy(pic_path, os.path.join(work_folder, os.path.basename(pic_path)))
    mark("prepare_workspace", t0)

    # 定义各种参数
    # 自动选择设备：优先使用 CUDA，不可用时回退到 CPU。
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    # 指定了使用的编码器的名称，这里是 'resnet50'
    # # 编码器通常是一个预训练的神经网络，用于提取图像特征
    ENCODER = "resnet50"
    # 指定了是否使用预训练编码器的权重，这里是 'imagenet'，表示使用 ImageNet 数据集上训练的权重
    ENCODER_WEIGHTS = "imagenet"
    preprocessing_fn = smp.encoders.get_preprocessing_fn(ENCODER, ENCODER_WEIGHTS)
    select_class_rgb_values = np.array([[0, 0, 0], [255, 255, 255]])
    x_test_dir = work_folder
    y_test_dir = work_folder

    # 模型路径
    model_path = "resources/best_model.pth"

    feature_root = os.path.join('result', 'satellite')
    time_tag = current_time.strftime("%Y%m%d_%H%M%S")
    task_suffix = uuid.uuid4().hex[:3]
    output_root = os.path.join(feature_root, f'task_{time_tag}_{task_suffix}')
    os.makedirs(feature_root, exist_ok=True)
    os.makedirs(os.path.join(output_root, 'gmns'), exist_ok=True)
    os.makedirs(os.path.join(output_root, 'temp', 'success'), exist_ok=True)

    # 定义数据增强、预处理函数
    def get_validation_augmentation():
        # 为了确保图像的高度和宽度都能被32整除，添加了足够的填充
        test_transform = [
            album.PadIfNeeded(
                min_height=1536, min_width=1536, always_apply=True, border_mode=0
            ),
        ]
        return album.Compose(test_transform)

    def get_preprocessing(preprocessing_fn=None):
        # 用于构建数据预处理的转换流水线
        """
        构建数据预处理转换
        Args:
            preprocessing_fn (可调用函数): 数据标准化函数
                (可以针对每个预训练的神经网络进行特定设置)
        返回:
            转换: albumentations.Compose
        """
        _transform = []
        if preprocessing_fn:
            _transform.append(album.Lambda(image=preprocessing_fn))
            # 使用了 Albumentations 库中的 Lambda 转换
            # Lambda 转换允许您应用自定义的函数来处理图像
        _transform.append(album.Lambda(image=to_tensor, mask=to_tensor))
        return album.Compose(_transform)

    def to_tensor(x, **kwargs):
        return x.transpose(2, 0, 1).astype("float32")
        # 这是一个辅助函数，用于将输入 x 转换为张量格式
        # 它将图像的维度从 (height, width, channels) 调整为 (channels, height, width)
        # 并将数据类型转换为浮点数类型。

    # 定义辅助函数
    # 用于数据可视化的辅助函数
    def visualize(**images):
        """
        Plot images in one row
        """
        n_images = len(images)
        plt.figure(figsize=(20, 8))
        for idx, (name, image) in enumerate(images.items()):
            plt.subplot(1, n_images, idx + 1)
            plt.xticks([])
            plt.yticks([])
            # get title from the parameter names
            plt.title(name.replace("_", " ").title(), fontsize=20)
            plt.imshow(image)
        plt.close()

    # 将分割图像的标签进行独热编码
    def one_hot_encode(label, label_values):
        """
        将分割图像的标签数组转换为独热编码格式，
        通过将每个像素值替换为长度为类别数的向量
        # 参数
            label：2D数组，代表分割图像的标签
            label_values

        # 返回
            一个2D数组，其宽度和高度与输入相同，
            但深度为类别数
        """

        semantic_map = []
        for colour in label_values:
            equality = np.equal(label, colour)
            # 比较输入的标签图像 label 中的每个像素是否与当前类别颜色相等
            # 这将产生一个布尔数组，其中像素等于该颜色的地方为True，否则为False
            class_map = np.all(equality, axis=-1)
            semantic_map.append(class_map)
        semantic_map = np.stack(semantic_map, axis=-1)
        # 将 semantic_map 列表中的单通道数组堆叠在一起，以生成独热编码的分割标签
        # 每个通道对应一个类别，通道中的像素值为1表示像素属于该类别，为0表示不属于

        return semantic_map

    # 在标签或预测中执行反向独热编码
    def reverse_one_hot(image):
        """
        将一个深度为类别数的独热编码格式的2D数组转换为只有一个通道的2D数组，
        其中每个像素值表示分类的类别标识。
        # 参数
            image: 独热编码格式的图像

        # 返回
            一个2D数组，其宽度和高度与输入相同，
            但深度为1，其中每个像素值表示分类的类别标识。
        """

        x = np.argmax(image, axis=-1)
        # np.argmax 函数返回沿着指定轴（axis=-1 表示最后一个轴，通常是深度）的最大值的索引
        # 在这里，它用于找到每个像素在多通道中具有最大值的通道
        return x

    # 对反向独热编码输出进行颜色编码
    def colour_code_segmentation(image, label_values):
        """
        给定一个包含类别标识的单通道数组，对分割结果进行颜色编码。
        # 参数
            image: 单通道数组，其中每个值表示类别标识。
            label_values: 包含类别标签对应颜色的列表。

        # 返回
            用于分割可视化的颜色编码图像。
        """
        colour_codes = np.array(label_values)
        x = colour_codes[image.astype(int)]
        return x

    # 用于将填充过的图像或mask裁剪（center crop）到指定的目标图像尺寸
    def crop_image(image, target_image_dims=[1500, 1500, 3]):
        target_size = target_image_dims[0]
        image_size = len(image)
        padding = (image_size - target_size) // 2

        if padding < 0:
            return image

        return image[
               padding: image_size - padding,
               padding: image_size - padding,
               :,
               ]

    # 定义了一个名为 RoadsDataset 的自定义数据集类，
    # 用于加载图像和相应的分割掩码，并对它们进行预处理和数据增强
    class RoadsDataset(torch.utils.data.Dataset):
        """
        马萨诸塞州道路数据集。读取图像，应用数据增强和预处理转换。

        Args:
            images_dir (str): 图像文件夹的路径
            masks_dir (str): 分割掩码文件夹的路径
            class_rgb_values (list): 选择类别的RGB值，用于从分割掩码中提取
            augmentation (albumentations.Compose): 数据转换流水线
                (例如翻转、缩放等)
            preprocessing (albumentations.Compose): 数据预处理
                (例如归一化、形状调整等)
        """

        def __init__(
                self,
                images_dir,
                masks_dir,
                class_rgb_values=None,
                augmentation=None,
                preprocessing=None,
        ):
            self.image_paths = [
                os.path.join(images_dir, image_id)
                for image_id in sorted(os.listdir(images_dir))
            ]
            self.mask_paths = [
                os.path.join(masks_dir, image_id)
                for image_id in sorted(os.listdir(masks_dir))
            ]

            self.class_rgb_values = class_rgb_values
            self.augmentation = augmentation
            self.preprocessing = preprocessing

        def __getitem__(self, i):
            # 从文件加载图像和掩码
            image = cv2.cvtColor(cv2.imread(self.image_paths[i]), cv2.COLOR_BGR2RGB)
            mask = cv2.cvtColor(cv2.imread(self.mask_paths[i]), cv2.COLOR_BGR2RGB)

            # 对掩码进行独热编码，将其转换为一个浮点数数组
            mask = one_hot_encode(mask, self.class_rgb_values).astype("float")

            # 如果提供了数据增强的转换流水线，则应用数据增强
            if self.augmentation:
                sample = self.augmentation(image=image, mask=mask)
                image, mask = sample["image"], sample["mask"]

            # 如果提供了数据预处理的转换流水线，则应用数据预处理
            if self.preprocessing:
                sample = self.preprocessing(image=image, mask=mask)
                image, mask = sample["image"], sample["mask"]

            return image, mask

        def __len__(self):
            # 返回长度
            return len(self.image_paths)

    t0 = time.perf_counter()
    best_model = _get_cached_model(model_path, DEVICE)
    print("模型已就绪")
    mark("load_or_reuse_model", t0)

    # 创建用于测试的数据加载器 (with preprocessing operation: to_tensor(...))
    t0 = time.perf_counter()
    test_dataset = RoadsDataset(
        x_test_dir,
        y_test_dir,
        augmentation=get_validation_augmentation(),  # 返回一个数据增强流水线
        preprocessing=get_preprocessing(preprocessing_fn),
        # 使用resnet50架构，在imagenet上的预训练参数
        class_rgb_values=select_class_rgb_values,
    )

    # 仅在调试模式下创建可视化数据集，避免重复读图和预处理开销
    test_dataset_vis = None
    if debug_visualization:
        test_dataset_vis = RoadsDataset(
            x_test_dir,
            y_test_dir,
            augmentation=get_validation_augmentation(),
            class_rgb_values=select_class_rgb_values,
        )
    mark("build_dataset", t0)

    t0 = time.perf_counter()
    for idx in range(len(test_dataset)):
        image, gt_mask = test_dataset[idx]
        image_vis = None
        if debug_visualization and test_dataset_vis is not None:
            image_vis = crop_image(test_dataset_vis[idx][0].astype("uint8"))
        x_tensor = torch.from_numpy(image).to(DEVICE).unsqueeze(0)

        # 预测测试图
        with torch.inference_mode():
            pred_mask = best_model(x_tensor)
        pred_mask = pred_mask.detach().squeeze().cpu().numpy()

        # 将预测出来的pred_mask从'CHW'转换为'HWC'格式
        pred_mask = np.transpose(pred_mask, (1, 2, 0))

        # pred_road_heatmap = pred_mask[:,:,select_classes.index('road')]
        pred_mask = crop_image(
            colour_code_segmentation(reverse_one_hot(pred_mask), select_class_rgb_values)
        )

        # 转换为二值图像
        binary_pred_mask = (pred_mask > 0).astype(np.uint8)
        binary_pred_mask = binary_pred_mask * 255

        # 保存黑白颠倒后的图（白底黑路），inverted_image 是 3D NumPy 数组
        save_path_1 = os.path.join(work_folder, f"inverted_binary_pred_{idx}.png")
        inverted_image = 255 - binary_pred_mask
        cv2.imwrite(save_path_1, inverted_image)

        # 将 gt_mask 从 `CHW` 转换为 `HWC` 格式
        gt_mask = np.transpose(gt_mask, (1, 2, 0))
        gt_mask = crop_image(
            colour_code_segmentation(reverse_one_hot(gt_mask), select_class_rgb_values)
        )

        if debug_visualization and image_vis is not None:
            visualize(
                original_image=image_vis,
                ground_truth_mask=gt_mask,
                predicted_mask=pred_mask,
                # predicted_road_heatmap = pred_road_heatmap
            )
    mark("model_inference", t0)

    print("生成的二值图路径:", save_path_1)
    print("开始识别角点...")

    # 接下来使用inverted_image进行后续操作：识别角点，生成gmns文件

    t0 = time.perf_counter()
    # 得到 inverted_image 的灰度图 gray_image（2D NumPy数组）
    gray_image = cv2.cvtColor(inverted_image, cv2.COLOR_BGR2GRAY)

    # 角点检测时点的优化距离(建议取二值图的线宽的一半，2~5?）
    line_width = 3  # 角点检测时点的优化距离(建议取二值图的线宽的一半，2~5?）

    # 其它参数，可调
    maxCorners = 1000
    qualityLevel = 0.01
    minDistance = 30
    blockSize = 30
    useHarrisDetector = False
    k = 0.02

    gray_img_name = os.path.join(output_root, 'gray_image.jpg')    # 保存灰度图名字
    temp_save_name = os.path.join(output_root, 'temp_result.jpg')  # 保存临时参考图
    img_save_name = os.path.join(output_root, 'jdjc_result.jpg')   # 保存角点检测图名字
    best_img_name = os.path.join(output_root, 'best_result.jpg')   # 保存结果图名字

    # 0、保存灰度图，方便 resize 函数调用
    cv2.imwrite(gray_img_name, gray_image)

    # 1、resize图片，输入路径，输出 800*800 的 OpenCV 图
    gray_image = resize_image(gray_img_name)

    # 2、边缘检测得到二值图, temp_save_name是边缘检测结果，更适合作为误差判断参考
    # 经过测试，应该加上这一步
    gray_image_byjc = byjc(gray_image, temp_save_name)
    mark("preprocess_post_seg", t0)

    # 3、角点检测得到角点corners.csv文件, 返回优化好的数组
    t0 = time.perf_counter()
    best_xy_list = jdjc(gray_image_byjc, img_save_name, line_width
                        , maxCorners, qualityLevel, minDistance, blockSize, useHarrisDetector, k)
    mark("corner_detection", t0)

    print("角点识别完成，并已保存识别结果图，开始遍历角点并连线...")

    # 4、画图，并生成link.csv文件
    # min_mse 指允许画线的最小误差阈值，意在防止重复连线。越大，对短线更严格，但更不容易出现重复连接
    # target 指线允许连接的距离的平方。越大允许连接的线越远，但同时计算速度越慢。当出现有断线时，可尝试增大该值。
    t0 = time.perf_counter()
    draw_timing = draw(best_xy_list, temp_save_name, best_img_name, min_mse=40, target=62500, output_root=output_root)
    mark("draw_links", t0)

    t0 = time.perf_counter()
    geojson_path = os.path.join(output_root, 'road_network.geojson')
    write_network_geojson(
        geojson_path,
        os.path.join(output_root, 'gmns', 'corners.csv'),
        os.path.join(output_root, 'gmns', 'link.csv'),
    )
    mark("write_geojson", t0)

    print("已完成角点间连线识别，并已生成gmns文件")

    # 5、将生成的gmns文件夹压缩为zip文件
    t0 = time.perf_counter()
    zip_file_path = os.path.join(output_root, 'gmns.zip')
    with zipfile.ZipFile(zip_file_path, 'w') as zipf:
        # 添加 corners.csv
        zipf.write(os.path.join(output_root, 'gmns', 'corners.csv'), 'gmns/corners.csv')
        # 添加 link.csv
        zipf.write(os.path.join(output_root, 'gmns', 'link.csv'), 'gmns/link.csv')
    mark("zip_outputs", t0)

    total_cost = round(time.perf_counter() - total_start, 4)
    print("[satellite_timing]", stage_cost, "total", total_cost, "s")
    if draw_timing is not None:
        print("[draw_timing]", draw_timing)

    # 返回生成的gmns文件夹压缩包路径
    return zip_file_path, best_img_name, geojson_path

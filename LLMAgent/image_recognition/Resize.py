from PIL import Image
import numpy as np
import cv2


def resize_image(file):
    # 打开图片
    image = Image.open(file)
    # 获取原始图片尺寸
    original_width, original_height = image.size
    # 计算新的尺寸，使其符合1:1比例
    new_width = 800
    new_height = 800
    # 计算原始图片的宽高比
    original_aspect_ratio = original_width / original_height

    # 如果更宽，限制高为new_height = 800
    if original_aspect_ratio > 1:
        new_ = int(image.width * (new_height / image.height))
        image = image.resize((new_, new_height))

        left = int((image.width - new_height) / 2)
        image = image.crop((left, 0, left + new_height, new_height))
    # 如果更高，限制宽为new_width = 800
    else:
        new_ = int(image.height * (new_width / image.width))
        image = image.resize((new_width, new_))

        height = int((image.height - new_width) / 2)
        image = image.crop((0, height, new_width, height + new_width))

    # 将Pillow图像对象转换为NumPy数组
    image_np = np.array(image)
    image.close()

    # 将NumPy数组转换为OpenCV图像对象
    image_cv2 = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

    return image_cv2

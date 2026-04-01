import csv
import cv2
import os
import numpy as np

def jdjc(img,img_save,line_width,maxCorners,qualityLevel,minDistance,blockSize,useDetector,k_):
    # 角点检测
    corners = cv2.goodFeaturesToTrack(img,maxCorners,qualityLevel,minDistance,blockSize,useHarrisDetector = useDetector,k = k_)

    img_size = img.shape
    image_copy = np.zeros(img_size, dtype='uint8') + 255
    best_mse = mse(img, image_copy)
    best_xy_list = []

    corners = np.int0(corners)
    for i in corners:
        x, y = i[0]
        temp_mse = best_mse
        best_xy = (x, y)
        for i in [-line_width, 0, line_width]:
            for j in [-line_width, 0, line_width]:
                image_temp = image_copy.copy()
                cv2.circle(image_temp, (x + i, y + j), line_width*2, (0, 0, 0), -1)
                currrent_mse = mse(image_temp, img)
                # 找到最好的了
                if currrent_mse < temp_mse:
                    temp_mse = currrent_mse
                    best_xy = (x + i, y + j)
        best_xy_list.append(best_xy)

    # # 检查是否存在名为"result"的文件夹，如果不存在，则创建它
    # 已在main.recognition中创建，故注释掉
    # results_dir = 'result'
    # if not os.path.exists(results_dir):
    #     os.makedirs(results_dir)

    # 绘制角点
    for i in best_xy_list:
        x,y = i
        # 输出识别到的点的坐标
        # print(x,y,img.shape)
        cv2.circle(img,(int(x),int(y)),10,(0,0,0),2)

    # 图片保存
    cv2.imwrite(img_save, img)
    return best_xy_list


def mse(image1, image2):
    err = np.sum((image1.astype("float") - image2.astype("float")) ** 2)
    err /= float(image1.shape[0] * image1.shape[1])
    return err
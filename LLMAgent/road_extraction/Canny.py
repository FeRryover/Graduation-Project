import cv2

def byjc(image,temp_save_name):


    # 降噪 + 变成灰度图
    gray_image = cv2.fastNlMeansDenoising(image, h=10, searchWindowSize=21, templateWindowSize=7)
    # 边缘检测
    edges = cv2.Canny(gray_image, 100, 200)  # 这里的参数可以根据需要进行调整
    # 填充边缘区域，使边缘变为实心
    filled_edges = cv2.dilate(edges, None, iterations=2)  # 根据需要可以调整iterations的值(线条膨胀次数）
    # 反转图像颜色，将黑底白线改为白底黑线
    inverted_filled_edges = cv2.bitwise_not(filled_edges)
    cv2.imwrite(temp_save_name,inverted_filled_edges)
    return inverted_filled_edges
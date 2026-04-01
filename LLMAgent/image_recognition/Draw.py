import numpy as np
import cv2, csv, math, operator
import os

# 中间过程的图片保存，不需要时前面加上return
def temp_save(flag, name, image):
    return
    cv2.imwrite(name, image)
    return flag+1

# 调试画图。不需要时前面加上return
def temp_draw(img, point_score_n, point_score_2,name):
    for i in point_score_n:
        x, y = i
        cv2.circle(img, (int(x), int(y)), 10, (255, 0, 0), 2)
    for i in point_score_2:
        x, y = i
        cv2.circle(img, (int(x), int(y)), 10, (0, 0, 255), 2)
    cv2.imwrite(name, img)

# 定义MSE误差计算函数
def mse(image1, image2):
    err = np.sum((image1.astype("float") - image2.astype("float")) ** 2)
    err /= float(image1.shape[0] * image1.shape[1])
    return err

# min_mse越大，对急短线更严格，但更不容易出现重复连接
# n_point 指的是对二次连接点 → 重要点的判断能力，以及删除重要点之间不重要点的精度。值越大，判断越严格，同时删除不重要点的能力越强。
def draw(corners, img_name, best_image_name, min_mse = 40, target = 62500, n_point = 10, output_root='result'):
    # 读取图片
    img = cv2.imread(img_name)

    # 画线线宽，图片尺寸
    line_width = 7
    img_size = img.shape

    # 求出白纸的初始best_mse
    image_copy = np.zeros(img_size, dtype='uint8') + 255
    best_mse = mse(img, image_copy)

    # 1、计算所有两点间距离。target值表示阈值, 超过这个距离的点将不会被连接
    temp_dict, point_score = dict(), dict()
    for i in range(len(corners)):
        for j in range(i + 1, len(corners)):
            point_1 = corners[i]
            point_2 = corners[j]
            l = (point_1[0] - point_2[0]) ** 2 + (point_1[1] - point_2[1]) ** 2
            if l <= target:
                temp_dict[(point_1, point_2)] = l


    # 2、按距离排序
    # 使用sorted函数根据值对字典进行排序
    sorted_items = sorted(temp_dict.items(), key=operator.itemgetter(1))
    # 获取排序后的键（x, y）列表
    sorted_list = [item[0] for item in sorted_items]

    # 检查需要创建的文件夹  (检查是否存在名为"result"的文件夹，如果不存在，则创建它)
    dir_name = [
        output_root,
        os.path.join(output_root, 'gmns'),
        os.path.join(output_root, 'temp'),
        os.path.join(output_root, 'temp', 'success'),
    ]
    for dir in dir_name:
        if not os.path.exists(dir):
            os.makedirs(dir)

    # 3、按距离连线
    connect = dict()  # connect是保存连接关系的字典。主要用于检测直线拐点。
    flag = 0  # temp计数器
    # 连接、分点、剔除不必要点，返回真正的corners
    for points in sorted_list:
        point_1 = points[0]
        point_2 = points[1]
        # 在复制的图像上添加连接线
        image_temp = image_copy.copy()
        cv2.line(image_copy, point_1, point_2, (0, 0, 0), line_width)
        # 计算当前图像的MSE误差
        current_mse = mse(img, image_copy)
        # 如果当前误差更小，更新最佳误差和最佳图像，为避免重复连线：阈值最小应进步min_mse
        if current_mse < best_mse and (best_mse - current_mse) > min_mse:
            # 调试，保存中间图片
            flag = temp_save(flag, os.path.join(output_root, 'temp', 'success', f'{flag}-{corners.index(point_1)}to{corners.index(point_2)}-{current_mse:.2f}-{best_mse:.2f}.jpg'), image_copy)
            # 记录每个点的连接次数，同时给两个点互相添加相连关系：
            point_score_or_connect(point_1, point_2, point_score, connect)
            # 记录误差
            best_mse = current_mse
        else:
            # 误差没有变得更小，所以移除连接线以继续遍历
            image_copy = image_temp.copy()

    # 得到了每个点的连接次数point_score。分离所有连接次数2与非2的点
    point_score_2, point_score_n = list(), list()
    for key in point_score:
        if point_score[key] == 2:
            point_score_2.append(key)
        else:
            point_score_n.append(key)

    # 从连接次数2的点中提取直角拐弯的点，放入重要点集合中
    i = 0
    while i < len(point_score_2):
        point_2 = point_score_2[i]
        result, distance = point_between_two_points(connect[point_2][0], connect[point_2][1], point_2)
        if distance > n_point:
            point_score_n.append(point_2)
            point_score_2.remove(point_2)
            i -= 1
        i += 1

    # 已经分离了所有重要点和非重要点。绘制角点，调试
    temp_draw(image_copy.copy(), point_score_n, point_score_2, os.path.join(output_root, 'jdjc_color_result.jpg'))

    # 寻找两个 相互连接 的 重要点
    point_n2n = list()
    for points in sorted_list:
        if points[0] in point_score_n and points[1] in point_score_n:
            point_n2n.append(points)

    # 删除所有两个相互连接的重要点之间的不重要点（弧线上的不重要点不会被处理）
    for points in point_n2n:
        point_n1 = points[0]
        point_n2 = points[1]
        i = 0
        while i < len(point_score_2):
            point_2 = point_score_2[i]
            result, distance = point_between_two_points(point_n1, point_n2, point_2)
            if result and distance < n_point:
                corners.remove(point_2)
                point_score_2.pop(i)
                i -= 1
            i += 1

    # 已经删除了所有不重要点。绘制角点，调试
    temp_draw(image_copy.copy(), point_score_n, point_score_2, os.path.join(output_root, 'jdjc_best_result.jpg'))

    # 统一坐标尺度：corners.csv 与 link.csv 的 geometry 都采用 1e-6 缩放坐标
    coord_scale = 1e-6

    # 创建corners.csv 并写入数据
    csv_file_path = os.path.join(dir_name[1], 'corners.csv')
    with open(csv_file_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['node_id', 'x_coord', 'y_coord'])  # 写入标题行
        for i in range(len(corners)):
            x, y = corners[i]
            csvwriter.writerow([i, f"{x * coord_scale:.6f}", f"{y * coord_scale:.6f}"])

    # 接下来开始清洗后的画图，并保存数据。
    best_image = None
    image_copy = np.zeros(img_size, dtype='uint8') + 255
    best_mse = mse(img, image_copy)  # 求出白纸的初始best_mse

    # 1、计算所有两点间距离。target值表示阈值, 超过这个距离的点将不会被连接
    temp_dict = dict()
    for i in range(len(corners)):
        for j in range(i + 1, len(corners)):
            point_1 = corners[i]
            point_2 = corners[j]
            l = (point_1[0] - point_2[0]) ** 2 + (point_1[1] - point_2[1]) ** 2
            if l <= target:
                temp_dict[(point_1, point_2)] = l


    # 2、按距离排序
    # 使用sorted函数根据值对字典进行排序
    sorted_items = sorted(temp_dict.items(), key=operator.itemgetter(1))
    # 获取排序后的键（x, y）列表
    sorted_list = [item[0] for item in sorted_items]


    # 3、按距离连线。创建link.csv 并写入数据
    csv_file_path = os.path.join(dir_name[1], 'link.csv')
    with open(csv_file_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['link_id', 'from_node_id', 'to_node_id', 'length', 'geometry'])  # 写入标题行
        link_id = 0
        # 经纬度坐标，中心点设置
        converter = CoordinateConverter(0, 0, coord_scale, coord_scale)
        for points in sorted_list:
            point_1 = points[0]
            point_2 = points[1]
            # 在复制的图像上添加连接线
            image_temp = image_copy.copy()
            cv2.line(image_copy, point_1, point_2, (0, 0, 0), line_width)
            # 计算当前图像的MSE误差
            current_mse = mse(img, image_copy)
            # 如果当前误差更小，更新最佳误差和最佳图像
            if current_mse < best_mse and (best_mse - current_mse) > min_mse:
                # 调试，保存中间图片
                flag = temp_save(flag, os.path.join(output_root, 'temp', 'success', f'{flag}-{corners.index(point_1)}to{corners.index(point_2)}-{current_mse:.2f}-{best_mse:.2f}.jpg'), image_copy)
                best_mse = current_mse
                best_image = image_copy.copy()
                # 经纬度转化
                longitude1, latitude1 = converter.convert_to_coordinates(point_1[0], point_1[1])
                longitude2, latitude2 = converter.convert_to_coordinates(point_2[0], point_2[1])
                geometry = f'LINESTRING ({longitude1:.6f} {latitude1:.6f}, {longitude2:.6f} {latitude2:.6f})'
                csvwriter.writerow([link_id, corners.index(point_1), corners.index(point_2), round(math.sqrt(temp_dict[(point_1,point_2)]), 2), geometry])
                link_id += 1
            else:
                # 移除连接线以继续遍历
                image_copy = image_temp.copy()
    # 保存最佳图像
    cv2.imwrite(best_image_name, best_image)


# 记录每个点的连接次数，同时给两个点互相添加相连关系：
def point_score_or_connect(point_1, point_2, point_score, connect):
    point_score[point_1] = point_score.get(point_1, 0) + 1
    point_score[point_2] = point_score.get(point_2, 0) + 1
    connect[point_1] = connect.get(point_1, list())
    connect[point_1].append(point_2)
    connect[point_2] = connect.get(point_2, list())
    connect[point_2].append(point_1)


# 检测p2是否在n1和n2之间，并返回p2距离n1和n2连线的距离。用以判断三点是否共线。
def point_between_two_points(n1, n2, p2):
    A = np.array(n1)
    B = np.array(n2)
    C = np.array(p2)
    AB = B - A
    AC = C - A
    projection_length = np.dot(AC, AB) / np.dot(AB, AB)
    distance = np.linalg.norm(AC - projection_length * AB)
    if 0 <= projection_length <= 1:
        return True, distance
    else:
        return False, distance


# 将x-y坐标转换成经纬度。
class CoordinateConverter:
    def __init__(self, origin_longitude, origin_latitude, x_increment, y_increment):
        self.origin_longitude = origin_longitude
        self.origin_latitude = origin_latitude
        self.x_increment = x_increment
        self.y_increment = y_increment

    def convert_to_coordinates(self, x, y):
        longitude = self.origin_longitude + x * self.x_increment
        latitude = self.origin_latitude + y * self.y_increment
        return longitude, latitude
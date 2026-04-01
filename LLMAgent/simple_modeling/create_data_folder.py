import os
def create_data_folder(relative_folder_name):
    # 获取当前工作目录
    current_directory = os.getcwd()

    # 创建相对路径
    relative_path = os.path.join(current_directory, relative_folder_name)

    # 如果目录不存在，则创建它
    if not os.path.exists(relative_path):
        os.makedirs(relative_path)
        print(f"相对文件夹 '{relative_folder_name}' 已创建于当前工作目录下的 'result' 文件夹中。")
    else:
        print(f"相对文件夹 '{relative_folder_name}' 已存在于当前工作目录下。")
import os
import numpy as np
import pickle
import json
from openpyxl import Workbook
import csv
import time

def generate_3d_array():
    """
    生成10×18×70的三维数组A
    条件:
    1. p = 1-i/(39+k)
    2. A[i][j][k] = 1 - p^j
    3. 当i×j>k时，A[i][j][k] = 0

    在麻将游戏种
    i: 需要的牌的数量
    j: 剩余巡目
    k: 剩余牌的总数（包括其他玩家的手牌和牌堆）
    因此，A[i][j][k] 表示在当前状态下，需要i张牌，剩余j巡，剩余k张牌时，摸到需要的牌的概率。
    """


    # 定义数组维度
    i_dim, j_dim, k_dim = 10, 18, 55
    hands = 26
    # 创建全0数组，后续根据条件填充
    A = np.zeros((i_dim, j_dim, k_dim))
    
    # 遍历所有维度
    for i in range(i_dim):
        for j in range(j_dim):
            for k in range(k_dim):
                # 检查条件 i*j < k
                if i * j > k:
                    A[i][j][k] = 0
                else:
                    # 计算 p = i/(39+k)，注意避免除以0
                    if (hands + k) != 0:
                        p = 1 - i / (hands + k)
                        # 计算 A[i][j][k] = 1 - p^j
                        # 当j=0时，p^0=1，所以A[i][0][k] = 0
                        A[i][j][k] = 1 - (p ** j)
    
    return A

def print_array_statistics(A):
    """打印数组的基本统计信息"""
    print(f"数组维度: {A.shape}")
    print(f"非零元素数量: {np.count_nonzero(A)}")
    print(f"数组元素总数: {A.size}")
    print(f"最小值: {A.min():.6f}")
    print(f"最大值: {A.max():.6f}")
    print(f"平均值: {A.mean():.6f}")

# 生成数组
print("正在生成三维数组...")
A = generate_3d_array()
print_array_statistics(A)

# ========== 存储方法1: 保存为NumPy二进制文件（推荐） ==========
def save_numpy_binary(A, filename="3d_array.npy"):
    """保存为NumPy二进制文件"""
    np.save(filename, A)
    print(f"\n✅ NumPy二进制文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法2: 保存为Pickle文件 ==========
def save_pickle(A, filename="3d_array.pkl"):
    """保存为Python Pickle文件"""
    with open(filename, 'wb') as f:
        pickle.dump(A, f)
    print(f"✅ Pickle文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法3: 保存为JSON文件 ==========
def save_json(A, filename="3d_array.json"):
    """保存为JSON文件"""
    # 将numpy数组转换为Python列表
    A_list = A.tolist()
    with open(filename, 'w') as f:
        json.dump(A_list, f)
    print(f"✅ JSON文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法4: 保存为CSV文件 ==========
def save_csv(A, filename="3d_array.csv"):
    """保存为CSV文件（扁平化）"""
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['i', 'j', 'k', 'value'])
        
        for i in range(A.shape[0]):
            for j in range(A.shape[1]):
                for k in range(A.shape[2]):
                    writer.writerow([i, j, k, A[i][j][k]])
    
    print(f"✅ CSV文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法5: 保存为Excel文件 ==========
def save_excel(A, filename="3d_array.xlsx"):
    """保存为Excel文件（多个sheet）"""
    wb = Workbook()
    
    # 每个i值对应一个sheet
    for i in range(A.shape[0]):
        if i == 0:
            ws = wb.active
            ws.title = f"i={i}"
        else:
            ws = wb.create_sheet(title=f"i={i}")
        
        # 写入表头
        ws.append(['k/j'] + [f'j={j}' for j in range(A.shape[1])])
        
        # 写入数据
        for k in range(A.shape[2]):
            row = [f'k={k}'] + [A[i][j][k] for j in range(A.shape[1])]
            ws.append(row)
    
    wb.save(filename)
    print(f"✅ Excel文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法6: 硬编码为Python语句（不推荐，文件很大） ==========
def save_as_python_code(A, filename="array_hardcoded.py"):
    """将数组硬编码为Python语句"""
    with open(filename, 'w') as f:
        f.write("import numpy as np\n\n")
        f.write("# 三维数组，维度: 10×18×70\n")
        f.write("# 通过以下语句定义:\n")
        f.write("A = np.zeros((10, 18, 70))\n\n")
        
        count = 0
        for i in range(A.shape[0]):
            for j in range(A.shape[1]):
                for k in range(A.shape[2]):
                    if A[i][j][k] != 0:  # 只存储非零值以减小文件大小
                        f.write(f"A[{i}][{j}][{k}] = {A[i][j][k]:.10f}\n")
                        count += 1
        
        print(f"✅ Python硬编码文件已保存: {filename}")
        print(f"   非零元素数量: {count}")
        print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 存储方法7: 压缩存储 ==========
def save_compressed(A, filename="3d_array_compressed.npz"):
    """保存为压缩的NumPy文件"""
    np.savez_compressed(filename, array_3d=A)
    print(f"✅ 压缩NumPy文件已保存: {filename}")
    print(f"   文件大小: {os.path.getsize(filename) / 1024:.2f} KB")

# ========== 加载函数 ==========
def load_numpy_binary(filename="3d_array.npy"):
    """从NumPy二进制文件加载"""
    return np.load(filename)

def load_pickle(filename="3d_array.pkl"):
    """从Pickle文件加载"""
    with open(filename, 'rb') as f:
        return pickle.load(f)

def load_json(filename="3d_array.json"):
    """从JSON文件加载"""
    with open(filename, 'r') as f:
        data = json.load(f)
    return np.array(data)

# ========== 测试所有存储方法 ==========
if __name__ == "__main__":
    # print("\n" + "="*50)
    # print("存储方法比较:")
    # print("="*50)
    
    # 记录每种方法的存储时间和文件大小
    # methods = []
    
    # # 方法1: NumPy二进制
    # start = time.time()
    # save_numpy_binary(A)
    # methods.append(("NumPy二进制", time.time() - start, os.path.getsize("3d_array.npy")))
    
    # # 方法2: Pickle
    # start = time.time()
    # save_pickle(A)
    # methods.append(("Pickle", time.time() - start, os.path.getsize("3d_array.pkl")))
    
    # # 方法3: JSON
    # start = time.time()
    # save_json(A)
    # methods.append(("JSON", time.time() - start, os.path.getsize("3d_array.json")))
    
    # # 方法4: CSV
    # start = time.time()
    # save_csv(A)
    # methods.append(("CSV", time.time() - start, os.path.getsize("3d_array.csv")))
    
    # 方法5: Excel
    start = time.time()
    save_excel(A)
    # methods.append(("Excel", time.time() - start, os.path.getsize("3d_array.xlsx")))
    
    # # 方法6: 压缩存储
    # start = time.time()
    # save_compressed(A)
    # methods.append(("NumPy压缩", time.time() - start, os.path.getsize("3d_array_compressed.npz")))
    
    # # 方法7: 硬编码（只存储非零值）
    # start = time.time()
    # save_as_python_code(A)
    # methods.append(("Python硬编码", time.time() - start, os.path.getsize("array_hardcoded.py")))
    
    # 打印方法比较
    # print("\n" + "="*50)
    # print("存储方法性能比较:")
    # print("="*50)
    # print(f"{'方法':<15} {'时间(秒)':<10} {'文件大小(KB)':<12} {'推荐度':<10}")
    # print("-"*50)
    
    # for name, t, size in methods:
    #     size_kb = size / 1024
    #     # 推荐度评估
    #     if "NumPy压缩" in name:
    #         recommendation = "★★★★★"
    #     elif "NumPy二进制" in name:
    #         recommendation = "★★★★☆"
    #     elif "Pickle" in name:
    #         recommendation = "★★★☆☆"
    #     elif "JSON" in name:
    #         recommendation = "★★★☆☆"
    #     elif "Excel" in name:
    #         recommendation = "★★☆☆☆"
    #     elif "CSV" in name:
    #         recommendation = "★★☆☆☆"
    #     else:
    #         recommendation = "★☆☆☆☆"
        
    #     print(f"{name:<15} {t:<10.4f} {size_kb:<12.2f} {recommendation:<10}")
    
    # # 验证加载功能
    # print("\n" + "="*50)
    # print("验证数据加载功能:")
    # print("="*50)
    
    # # 从NumPy文件加载验证
    # loaded_A = load_numpy_binary()
    # if np.allclose(A, loaded_A):
    #     print("✅ NumPy二进制文件加载验证成功")
    # else:
    #     print("❌ NumPy二进制文件加载验证失败")
    
    # # 显示数组部分内容作为验证
    # print("\n数组A的部分内容示例:")
    # print("A[0][0][0:5]:", A[0][0][:5])
    # print("A[5][5][30:35]:", A[5][5][30:35])
    
    # # 验证条件：当i×j<k时，A[i][j][k] = 0
    # print("\n验证条件 i×j < k 时 A[i][j][k] = 0:")
    # test_cases = [
    #     (1, 1, 2),  # 1*1=1 < 2, 应该为0
    #     (2, 3, 7),  # 2*3=6 < 7, 应该为0
    #     (2, 3, 5),  # 2*3=6 > 5, 应该不为0
    # ]
    
    # for i, j, k in test_cases:
    #     value = A[i][j][k]
    #     condition = i * j < k
    #     print(f"  A[{i}][{j}][{k}] = {value:.6f}, i×j={i*j} < k={k} 为 {condition}, 验证{'通过' if (condition and value == 0) or (not condition and value != 0) else '失败'}")

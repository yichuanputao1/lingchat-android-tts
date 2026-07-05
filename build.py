# build.py (修复构建隔离错误版本)
import os
import sys
import requests
import zipfile
import subprocess
import shutil
from pathlib import Path

# --- 1. 配置区 ---
PYTHON_VERSION = "3.10.9" 
PYTHON_DIST_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# --- 2. 路径定义 ---
PROJECT_ROOT = Path(__file__).parent
PYTHON_EMBED_DIR = PROJECT_ROOT / "python-embed"
PYTHON_ZIP_PATH = PROJECT_ROOT / Path(PYTHON_DIST_URL).name
PIP_INSTALLER_PATH = PROJECT_ROOT / "get-pip.py"
FINAL_ZIP_NAME = "my_portable_app_windows"

# --- 3. 辅助函数 ---
def download_file(url, dest_path):
    """下载文件并显示进度条"""
    if dest_path.exists():
        print(f"✔️ 文件已存在: {dest_path.name}")
        return
    
    print(f"⏳ 正在下载 {url}...")
    try:
        from tqdm import tqdm
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        with open(dest_path, 'wb') as f, tqdm(
            desc=dest_path.name,
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                bar.update(len(chunk))
        print(f"✔️ 下载完成: {dest_path.name}")
    except ImportError:
        print("警告: 未安装 tqdm。将不显示进度条。请运行 `pip install tqdm`")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(response.content)
        print(f"✔️ 下载完成: {dest_path.name}")
    except requests.exceptions.RequestException as e:
        print(f"❌ 下载失败: {e}")
        sys.exit(1)


def run_command(cmd_list):
    """运行一个子进程命令并实时打印输出"""
    print(f"🏃 执行命令: {' '.join(map(str, cmd_list))}")
    process = subprocess.Popen(
        cmd_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    while True:
        line = process.stdout.readline()
        if not line:
            break
        print(line.strip())
    
    process.wait()
    if process.returncode != 0:
        print(f"❌ 命令执行失败，返回码: {process.returncode}")
        sys.exit(1)
    print("✔️ 命令执行成功!")


# --- 4. 主逻辑 ---
def main():
    print("--- 开始构建便携式 Python 应用 ---")

    # 步骤 1: 下载 Python 嵌入版
    download_file(PYTHON_DIST_URL, PYTHON_ZIP_PATH)

    # 步骤 2: 解压 Python
    if not PYTHON_EMBED_DIR.exists():
        print(f"📦 正在解压 {PYTHON_ZIP_PATH.name} 到 {PYTHON_EMBED_DIR}...")
        with zipfile.ZipFile(PYTHON_ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(PYTHON_EMBED_DIR)
        print("✔️ 解压完成。")
    else:
        print(f"✔️ Python 目录已存在: {PYTHON_EMBED_DIR}")

    # 步骤 3: 启用 site-packages
    print(f"🔧 正在查找 ._pth 文件以启用 site-packages...")
    try:
        pth_file = next(PYTHON_EMBED_DIR.glob("python*._pth"))
        print(f"   找到了: {pth_file.name}")
        
        # 读取并修改 ._pth 文件内容
        with open(pth_file, 'r+') as f:
            lines = f.readlines()
            f.seek(0)
            f.truncate()
            
            # 确保包含关键配置
            for line in lines:
                if line.strip() == "#import site":
                    f.write("import site\n")
                else:
                    f.write(line)
            
            # 添加项目路径
            if "../style_bert_vits2/\n" not in lines:
                f.write("../style_bert_vits2/\n")
            print("✔️ 已配置 ._pth 文件：启用 import site 并添加 ../style_bert_vits2/")
            
    except StopIteration:
        print(f"❌ 错误: 未找到 ._pth 文件")
        sys.exit(1)
            
    # 步骤 4: 安装 pip
    python_exe = PYTHON_EMBED_DIR / "python.exe"
    pip_exe = PYTHON_EMBED_DIR / "Scripts" / "pip.exe"
    
    if not pip_exe.exists():
        print("--- 正在为嵌入式 Python 安装 pip ---")
        download_file(PIP_URL, PIP_INSTALLER_PATH)
        run_command([str(python_exe), str(PIP_INSTALLER_PATH)])
        if PIP_INSTALLER_PATH.exists():
             PIP_INSTALLER_PATH.unlink()
        print("✔️ pip 安装成功。")
    else:
        print("✔️ pip 已安装。")
        
    # 步骤 5: 使用嵌入式 pip 安装依赖
    requirements_file = PROJECT_ROOT / "requirements.txt"
    if requirements_file.exists() and requirements_file.read_text().strip():
        print("--- 正在预安装构建工具 (setuptools, wheel, numpy) ---")
        
        # 【核心修改点】在这里加入 "numpy" 和 "cython"
        # 既然要源码编译，我们必须先手动把环境准备好
        run_command([str(python_exe), "-m", "pip", "install", "setuptools", "wheel", "numpy", "cython", "--no-warn-script-location"])
        
        print(f"--- 正在从 {requirements_file.name} 安装依赖 (禁用构建隔离) ---")
        run_command([str(python_exe), "-m", "pip", "install", "-r", str(requirements_file), "--no-build-isolation"])
        print("✔️ 依赖安装完成。")
    else:
        print("⚠️ 未找到 requirements.txt 或文件为空，跳过安装依赖。")
    
    # 步骤 6/7: 打包整个项目为 zip
    print(f"--- 正在将项目打包成 {FINAL_ZIP_NAME}.zip ---")
    # 删除旧的压缩包（如果存在）
    if (PROJECT_ROOT / f"{FINAL_ZIP_NAME}.zip").exists():
        (PROJECT_ROOT / f"{FINAL_ZIP_NAME}.zip").unlink()
        
    shutil.make_archive(
        base_name=FINAL_ZIP_NAME,
        format='zip',
        root_dir=PROJECT_ROOT
    )
    print(f"🎉 构建完成！最终产物: {PROJECT_ROOT / (FINAL_ZIP_NAME + '.zip')}")
    
    # 步骤 8: 清理临时文件
    print("--- 正在清理临时文件 ---")
    if PYTHON_ZIP_PATH.exists():
        PYTHON_ZIP_PATH.unlink()
    print("🧹 清理完成。")

if __name__ == "__main__":
    main()
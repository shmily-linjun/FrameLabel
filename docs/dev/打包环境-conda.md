# 用 Conda 构建 CPU / GPU 版可执行文件

仓库根目录提供两份环境文件：

| 文件 | 环境名 | 用途 |
|---|---|---|
| [`environment-cpu.yml`](../../environment-cpu.yml) | `xanylabeling-cpu` | 无显卡机器，CPU ONNX Runtime |
| [`environment-gpu.yml`](../../environment-gpu.yml) | `xanylabeling-gpu` | NVIDIA 显卡，默认 CUDA 12.x + cuDNN 9.x |

两份文件都安装 `dev` 依赖，因此包含 `PyInstaller`、`pytest`、`PySide6`（提供 `pyside6-lrelease`）等打包工具。**不要在同一环境中同时装 CPU 和 GPU 的 onnxruntime**。

## 0. 最常见的错误：不在仓库根目录执行

`conda env create -f environment-gpu.yml` 只负责找到 YAML 文件；**pip 子进程仍以你当前所在目录为工作目录**。如果当前目录不是仓库根，`-e .` 会指向那个目录：

```text
ERROR: file:///D:/cbg does not appear to be a Python project:
neither 'setup.py' nor 'pyproject.toml' found.
```

例如你在 `D:\cbg` 执行、仓库实际在 `D:\cbg\X-AnyLabeling-main`，先在 PowerShell 中确认：

```powershell
Get-Location
Test-Path .\pyproject.toml
```

必须有 `pyproject.toml`，否则先 `cd` 到仓库根：

```powershell
cd D:\cbg\X-AnyLabeling-main
Test-Path .\pyproject.toml
conda env create -f environment-gpu.yml
```

如果上一次已经留下不完整的环境，先删除再重来：

```powershell
conda env remove -n xanylabeling-gpu -y
```

也可以在仓库根目录用脚本自动切到正确目录（推荐）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_conda_env.ps1 -Device gpu
```

失败后重建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_conda_env.ps1 -Device gpu -Recreate
```

## 1. 前置条件

- Windows 10/11 64 位（本文以 Windows 打包为例）。
- 已安装 [Miniconda](https://docs.anaconda.com/miniconda/) 或 Anaconda。
- Git（克隆仓库）和 Git Bash（执行 `scripts/build_executable.sh`）。
- 打包安装包时额外需要 [Inno Setup](https://jrsoftware.org/isinfo.php) 6.7.3 或更高版本；只打单文件 exe 不需要。
- GPU 环境额外需要：
  - NVIDIA 驱动（建议 550 以上，以 ONNX Runtime 文档为准）；
  - CUDA 12.x Runtime；
  - cuDNN 9.x；
  - CUDA/cuDNN 的 `bin` 目录在 `PATH` 中。

## 2. CPU 环境

在仓库根目录执行：

```powershell
conda env create -f environment-cpu.yml
conda activate xanylabeling-cpu
```

验证：

```powershell
python -c "import sys, onnxruntime as ort; print(sys.version); print(ort.__version__); print(ort.get_available_providers())"
python -c "import PyInstaller, PyQt6, PySide6; print('build deps ok')"
pyside6-lrelease -version
```

CPU 环境应只看到 `CPUExecutionProvider`。

## 3. GPU 环境

先安装好 NVIDIA 驱动、CUDA 12.x Runtime 和 cuDNN 9.x，并确认 `nvidia-smi` 可用，然后在仓库根目录执行：

```powershell
conda env create -f environment-gpu.yml
conda activate xanylabeling-gpu
```

验证：

```powershell
python -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
```

应至少包含 `CUDAExecutionProvider`。如果只有 `CPUExecutionProvider`，依次检查：

```powershell
where.exe nvidia-smi
where.exe cudart64_12.dll
where.exe cudnn64_9.dll
pip show onnxruntime-gpu
pip show onnxruntime
```

- `pip show onnxruntime` 如果存在，说明混装了 CPU 版；卸载后重装：
  ```powershell
  pip uninstall -y onnxruntime onnxruntime-gpu
  pip install -e ".[gpu,dev]"
  ```
- `cudart64_12.dll` / `cudnn64_9.dll` 找不到时，把 CUDA/cuDNN 的 `bin` 加入 `PATH`，重新打开终端再验证。

### CUDA 13 或 11

`environment-gpu.yml` 默认使用 `[gpu]`（CUDA 12.x）。如果目标机是 CUDA 13.x 或 11.x，修改该文件中的 pip 行后**重建环境**：

```yaml
# CUDA 13.x
- -e .[gpu-cu13,dev]

# CUDA 11.x
- -e .[gpu-cu11,dev]
```

三个 extra 互斥，不要叠加安装。

## 4. 构建 exe

在 Git Bash 中、仓库根目录执行：

```bash
# CPU 单文件 exe
bash scripts/build_executable.sh win-cpu

# GPU 单文件 exe
bash scripts/build_executable.sh win-gpu
```

输出在 `dist/`，例如：

```text
dist/X-AnyLabeling-v4.3.2+fork.45-CPU.exe
dist/X-AnyLabeling-v4.3.2+fork.45-GPU.exe
```

需要安装包时：

```bash
# 需要 Inno Setup 6.7.3+
bash scripts/build_executable.sh win-cpu-installer
bash scripts/build_executable.sh win-gpu-installer
```

GPU 安装包默认按 `CUDA12` 打包；CUDA 13 使用：

```bash
X_ANYLABELING_VARIANT=CUDA13 bash scripts/build_executable.sh win-gpu-installer
```

> **GPU exe 不是完全绿色包**：当前 PyInstaller 规格收集 ONNX Runtime 的 Provider DLL，但 CUDA/cuDNN 运行库仍需目标机安装，或由你自行把对应 DLL 一并分发。只追求“复制即可运行”时，优先用 CPU 版 exe。

## 5. 更新与重建

项目依赖变化后，在仓库根目录更新环境：

```powershell
conda activate xanylabeling-cpu
conda env update -f environment-cpu.yml --prune
```

彻底重建（推荐，避免残留 CPU/GPU onnxruntime）：

```powershell
conda deactivate
conda env remove -n xanylabeling-cpu
conda env create -f environment-cpu.yml
```

GPU 环境同理，把环境名和文件名换成 `xanylabeling-gpu` / `environment-gpu.yml`。

如果 `conda env create` 的 pip 阶段没有在仓库根目录执行，`-e .` 会指向错误目录；进入仓库根目录后手动补一次：

```powershell
conda activate xanylabeling-cpu
python -m pip install -e ".[cpu,dev]"
```

## 6. 环境文件为什么没有锁死所有版本

`environment-cpu.yml` / `environment-gpu.yml` 跟随 `pyproject.toml` 的下界，便于不同机器上解析到兼容的新版本；真正发布前建议记录一次实际版本：

```powershell
python -m pip freeze > temporary/requirements-build-cpu.txt
```

如果目标机需要完全可复现的构建，可把该文件作为约束使用；不要把它提交成项目依赖清单，避免把本机 CUDA/驱动相关包带进其他机器。

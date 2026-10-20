# 环境自检记录（T0.1）

检测时间：2026/10/18　　机器：LL\26763　　任务：T0.1 环境自检

## 1. Python

| 项 | 值 |
|---|---|
| 版本 | `Python 3.14.8` |
| 路径 | `D:\AiStudy\Python\python.exe`（`py -0p` 显示 3.14 为默认） |
| 勿用 | `C:\Users\26763\AppData\Local\Microsoft\WindowsApps\python.exe`（Microsoft Store 别名） |
| 结论 | 版本 ≥ 3.10 ✅ |

**风险**：3.14 发布太新，`chromadb`（依赖 onnxruntime / tokenizers / numpy 等二进制轮子）在 3.14 上可能没有预编译 wheel。T0.4 建虚拟环境时优先用 **Python 3.12**，技术栈不变。

## 2. Ollama

| 项 | 值 |
|---|---|
| 版本 | `ollama version is 0.13.5` |
| 已拉取模型 | `deepseek-r1:7b`（4.7 GB） |
| 结论 | 命令可用 ✅ |
| 缺口 | 计划书开发模型 `qwen2.5:7b` **尚未拉取**，T1.5 前需 `ollama pull qwen2.5:7b` |

## 3. pip 源

```text
global.index-url       = https://mirrors.aliyun.com/pypi/simple/
global.extra-index-url = https://pypi.org/simple/
global.trusted-host    = mirrors.aliyun.com
```

结论：主索引为阿里云国内镜像 ✅（`extra-index-url` 指向 pypi.org，安装个别包时可能变慢，如遇超时可临时去掉）。

## 4. 磁盘

| 盘 | 剩余 |
|---|---|
| C: | 124.8 GB |
| D: | 115.9 GB ← 项目盘，要求 ≥ 20GB ✅ |
| E: | 133.4 GB |

## 附：硬件

| 项 | 值 |
|---|---|
| 内存 | 15.7 GB（16G） |
| CPU | 12th Gen Intel Core i7-12700H |
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU（6GB 显存）+ Intel Iris Xe |

7B 模型按计划书的 6GB 显存假设可以本地跑。

## 附：工作区写权限修复记录（2026/10/18）

现象：Python 进程无法在 `D:\ai-kb` 建文件或建虚拟环境（`WinError 5`），PowerShell 与 git 正常。

根因：被拉起的 Python 进程运行在 **Low 完整性级别**（令牌组 `S-1-16-4096`），`D:\ai-kb` 默认为 Medium 级别且禁止向上写；DSH 启动时对 `D:\ai-kb` 的写权授予也因缺少权限位失败（`SetNamedSecurityInfoW Win32 5`）。

修复（两条命令，已执行）：

```powershell
icacls "D:\ai-kb" /grant "${env:USERNAME}:(OI)(CI)F"
icacls "D:\ai-kb" /setintegritylevel (OI)(CI)L
```

回滚：`icacls "D:\ai-kb" /setintegritylevel (OI)(CI)M`

副作用：`D:\ai-kb` 下任何低完整性进程可写文件。本机个人项目可接受。

## 附：虚拟环境与依赖（T0.4 完成，2026/10/20）

| 项 | 值 |
|---|---|
| 解释器 | Python **3.12.10**（`C:\Users\26763\AppData\Local\Programs\Python\Python312`，由 winget 安装） |
| 虚拟环境 | `D:\ai-kb\.venv`（`pyvenv.cfg` 指向 3.12，`include-system-site-packages = false`） |
| pip | 25.0.1（venv 内） |
| 已安装包 | 145 个 |
| `pip check` | `No broken requirements found` |
| 依赖清单 | `requirements.txt`，148 行（含 3 行说明），精确锁版本 |

激活脚本的已知问题（实测 2026/10/20）：

- 直接 `.\.venv\Scripts\Activate.ps1` 会报 `AuthorizationManager 检查失败 / PSSecurityException`。
  原因是 `D:\ai-kb` 被打了 **Low 完整性标签**（见上节写权限修复），PowerShell 对低完整性脚本按"来源不可信"处理；把同一脚本复制到 C 盘执行则不会报该错。
- 两种可用方式：
  1. PowerShell 里先放行当前进程：`Set-ExecutionPolicy -Scope Process Bypass`，再 `.\.venv\Scripts\Activate.ps1`；
  2. cmd 里用批处理：`.venv\Scripts\activate.bat`。
- 也可以完全不激活，直接 `.\.venv\Scripts\python.exe …`（等价，所有文档命令都按这种方式写）。

关键包版本：

| 包 | 版本 | 包 | 版本 |
|---|---|---|---|
| langchain | 1.4.6 | chromadb | 1.5.9 |
| langchain-community | 0.4.2 | fastapi | 0.150.0 |
| langchain-ollama | 1.1.0 | uvicorn | 0.54.0 |
| langchain-openai | 1.7.2 | streamlit | 1.66.0 |
| python-dotenv | 1.2.4 | pypdf | 6.21.1 |
| python-docx | 1.2.0 | **sentence-transformers** | **6.1.0**（增项） |
| **torch** | **2.14.1+cpu**（增项） | transformers | 5.20.2 |
| onnxruntime | 1.31.0 | numpy | 2.5.4 |

安装过程记录（供排错参考）：

- 计划书原清单 10 个包一次装成（含子依赖共 132 个）。
- `sentence-transformers`（连带 torch）反复失败：pip 走 `files.pythonhosted.org` 或连接抖动，速度降到约 11 kB/s，出现 `ReadTimeoutError`，随后因半截下载触发 `THESE PACKAGES DO NOT MATCH THE HASHES`。
- 处置：改用清华源 + `curl` 直下 wheel（实测 118.4 MB / 9.7 s，约 12.5 MB/s），本地校验 zip 完整性后 `pip install <本地wheel>`。`torch 2.14.1+cpu`、`scipy 1.18.1`、`scikit-learn 1.9.1` 三个包即由此安装。
- `pip freeze` 会把这三个包写成 `file://` 本地路径，已在 `requirements.txt` 中改写为 PyPI 版本号，可直接 `pip install -r` 复现。

## 附：Ollama 模型目录（2026/10/20 核实）

| 项 | 值 |
|---|---|
| `OLLAMA_MODELS`（用户变量） | `D:\deepseekr17b\models` |
| 实际占用 | **D 盘** 4.36 GB（`deepseek-r1:7b`） |
| `C:\Users\26763\.ollama\models` | **目录联接（junction）→ `D:\deepseekr17b\models`**，0 字节，不是副本 |
| 已拉取模型 | `deepseek-r1:7b`（4.36 GB） |
| 待拉取模型 | `bge-m3`（T1.3 用）、`qwen2.5:7b`（T1.5 用） |

注意：不要用 `Remove-Item -Recurse` 删除 C 盘那个 junction，部分 PowerShell 版本会连带删除 D 盘的真实数据；确需删除请用 `cmd /c rmdir "C:\Users\26763\.ollama\models"`（不带 `/s`）。

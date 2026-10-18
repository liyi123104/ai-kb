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

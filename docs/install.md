# 手动安装教程

> [README](../README.md) 正文给了让智能体代劳的一条聚合命令。本文是手动逐步版，适合想看清每一步、或客户端目录结构特殊的用户。

## 前置要求

- Python 3.10+（仅标准库，零 pip 依赖）
- Windows / macOS / Linux 均可
- 一个支持 MCP 或 skills 的客户端（Claude、Codex、Pi 等）

## 第一步：克隆仓库

克隆到你客户端的 skills 目录。按客户端实际路径选择：

```bash
# Claude 为例
git clone https://github.com/caix84476-netizen/personal-understanding.git \
    ~/.claude/skills/personal-understanding

# Windows 上通常是
git clone https://github.com/caix84476-netizen/personal-understanding.git \
    %USERPROFILE%\.claude\skills\personal-understanding
```

也可以只 `pip install personal-understanding` 装服务端，但完整的「大脑」是 `SKILL.md` + 审计面板，**建议用 clone**。

## 第二步：初始化档案骨架

```bash
cd <克隆目标目录>
python scripts/init_archive.py
```

幂等，重复执行不会破坏已有档案。这一步在仓库内创建 `memory/`、`sources/` 等目录骨架（均已被 `.gitignore` 挡住，不会误提交）。

## 第三步：注册 MCP 服务

```bash
python scripts/install_mcp.py --auto
```

自动检测本机已装的客户端并写入 MCP 配置；幂等。Windows 下也可双击根目录的 `register-mcp.cmd`。

想手动核对装了什么：`install_mcp.py` 会把 `scripts/mcp_server.py`（stdio 服务端）注册进客户端配置，工具名形如 `personal_*`。

## 第四步：重启客户端

重启后 `personal_preflight_turn`、`personal_capture_user_turn`、`personal_catalog` 等 11 个工具上线。发一句「记住一下：我最近在学滑板」，能正常接住即安装成功。

## 第五步（可选）：审计面板

```bash
python scripts/open_dashboard.py
```

Windows 下可双击 `open-dashboard.cmd`。面板是纯本地静态页（`dashboard/`），可视化浏览时间线、实体、待回访、检索轨迹。

## 验证清单

- [ ] `python --version` ≥ 3.10
- [ ] `init_archive.py` 跑完无报错，`memory/` 目录出现
- [ ] `install_mcp.py --auto` 提示已注册
- [ ] 重启客户端后 `personal_*` 工具可见
- [ ] 发一条「记住……」消息，随后 `python mcp_test.py`（仓库自带验收驱动）或直接问「你还记得我刚说的吗」能回溯

## 升级

```bash
cd <仓库目录> && git pull
python scripts/init_archive.py   # 幂等，补新骨架
# 必要时 python scripts/install_mcp.py --auto 重新登记
```

## 卸载

从客户端 MCP 配置里移除 `personal-understanding` 条目，删除仓库目录即可。你的档案全在目录内的 `memory/` 和 `sources/`，删前记得备份——`python scripts/backup_archive.py` 会出一份带 SHA-256 清单的备份。

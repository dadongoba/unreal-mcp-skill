# unreal-mcp-skill

[English](README.md) · **简体中文**

> 一个面向不同 AI 客户端的 **标准 Agent Skill 与 MCP 运行时**，支持 Epic Toolsets 与原生 HTTP 后端适配。真机验证版本为 UE 5.8.3；UE 5.7 适配目前通过协议模拟测试，尚未完成真机验证。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 这是什么

一个可移植的知识包与 Python 运行时，通过 Epic 的 **ModelContextProtocol** 工具集操作 UE（实际工具集取决于引擎版本和启用的插件）。不同客户端可以使用 MCP、原生 Skills 或命令行接入：

- **蓝图 DSL 工作流** —— 创建蓝图、变量、函数、跨蓝图调用、编译、PIE 验证；一套类 Scheme 的 DSL（`write_graph_dsl`），含 27 条实战验证过的语法法则
- **场景 / 物理 / 碰撞** —— 组件选取规则、触发器模式、运行时物理激活
- **材质 / UMG / Niagara / Sequencer / PCG / ControlRig / 骨骼网格** —— 每个领域都有验证过的流程
- **一键连接（One-Click Connect）** —— `ue_connect.py` 自动诊断编辑器/端口/插件状态并帮你启动 UE（对新手友好）
- **踩坑法则库** —— 从真实故障复盘提炼出的 17 组法则（G1-G17）：调色板名与工具 id 的命名空间差异、Cast 节点命名陷阱、中文语言环境的显示名本地化、幽灵端口占用……
- **离线节点字典 + 检索工具** —— 1665 个节点的字典 + PIE 验证过的补充节点，秒级检索

每条规则都带有可信度标签：`[VERIFIED <日期> UE<版本>-<语言>]`（经 PIE 验证）、`[DOC]`（来自官方文档）或 `[UNVERIFIED]`（未验证）。

## 快速开始

1. **安装共享运行时**，在可信的仓库目录执行：
   ~~~text
   python scripts/unreal_mcp.py install --source .
   python scripts/unreal_mcp.py config
   python scripts/unreal_mcp.py doctor
   ~~~
   将生成的配置按客户端要求接入 MCP。支持 Skills 的客户端再安装小型入口：
   `python scripts/unreal_mcp.py adapter --skill-dir <客户端技能目录>/unreal-mcp`。
   详见[通用运行时与接入标准](references/universal-runtime.md)。
2. **准备一个 UE5.8+ 项目**，其 `.uproject` 需启用以下插件（技能可在你同意后自动添加）：
   `ModelContextProtocol` · `ToolsetRegistry` · `EditorToolset` · `PythonScriptPlugin` · `AllToolsets`
3. **注册目标编辑器**，需要 Python 3.10+，运行库仅使用标准库：
   ~~~text
   python scripts/ue_connect.py register --instance main --project <PROJECT.uproject> --engine <UE_ROOT> --port 8011
   python scripts/ue_connect.py launch --instance main
   python scripts/ue_connect.py wait --instance main
   ~~~
   多个编辑器使用[多实例连接](references/multi-instance.md)。受管写操作必须先绑定任务；旧版直接写调用需要迁移。

## v3.19 后端与更新发现（尚未发布）

- 新增 ue_capabilities，根据实际工具 Schema 识别 Epic、Avatar，或显式使用原生 MCP 调用。详见[兼容范围与验证证据](references/backends.md)。
- ue_status 自动检查原仓库的稳定 Release，多个客户端共享 24 小时缓存；ue_check_update 可立即刷新或离线读取。
- 网络失败明确返回“未知”；只有旧源码 Release、没有可升级安装包时，返回“尚未发布便携包”。
- 检查不会安装更新；更新仍受活动任务保护，支持回滚，并提示已有客户端重连。详见[更新发现机制](references/update-discovery.md)。

## 共享运行层

- 提供标准 MCP stdio 和带认证的本机 HTTP 接口，核心不依赖特定 AI 软件。
- 任务归属各自 MCP 会话；不支持 Skills 的客户端也可检索、读取正式知识。
- 核心统一安装，客户端仅保留小型入口；提供诊断和版本检查。
- 安装校验文件清单与摘要，任务中禁止切换版本，可回退上一包。
- 社区经验经过候选、复现、审核和发布，再进入各客户端使用的知识库。

- 按实例和项目协调写入，校验监听进程身份，分别建立会话。
- 支持 JSON/SSE，区分工具错误；写入结果未知时不盲目重放。
- 本地经验队列、脱敏检查，以及用户明确启用后的原仓库投稿。
- 为命令行宿主提供可恢复的[任务结束包装器](references/experience-contribution.md)。
- 本机状态放在 ~/.unreal-mcp，与技能安装目录分离。

投稿工作流需要先合入 master，并由仓库所有者开启 Actions 创建 PR 的权限。
默认只在本机保存；每位用户自行选择是否启用公开上传。
详见[投稿设置与隐私说明](references/experience-contribution.md)。

验证范围：模拟 HTTP/SSE、本地状态回归、官方 SDK 互通，以及
[Windows UE 5.8.3 真实双编辑器测试](references/validation/ue583-dual-editor-20261019.md)：
无渲染模式下的路由、蓝图保存与读回、PIE 行为已验证；渲染、地图持久化和公开入库链路不在此次通过范围内。


桥接服务可先于 UE 启动；开始编辑任务前，需要注册目标实例并启动 UE。
修改 MCP 配置或切换运行版本后，重新连接客户端。工具发现时机由具体宿主决定。

## ⚠️ 已知限制：请使用英文版编辑器界面

本技能是基于 **英文（EN）编辑器语言** 的 UE 5.8 验证的。
通过 MCP 驱动编辑器时，**不要**把编辑器切成中文（或其他本地化界面）：

- 节点的 `type_id` 是按调色板/注册表名称匹配的。在本地化编辑器里，部分类别会被改名（例如 Cast 类别 `Utilities|Casting|` 在中文编辑器里显示为 `工具|Casting|`），导致按 id 创建节点静默失败。
- 本仓库中每条已验证的规则都标注为 `[VERIFIED ... UE5.8-EN]` —— 仅在英文语言环境的编辑器上验证过。

**如果你的编辑器是中文**：通过 `Edit → Editor Preferences → Region & Language → Editor Language = English` 切换，然后重启编辑器。注意控制台命令 `culture = en` **无效** —— 它不会影响蓝图节点的显示名（详见 `references/ue_conventions.md` 第 10 节）。

## 平台支持

| | Windows | macOS |
|---|---|---|
| 启动编辑器 | `UnrealEditor.exe` | `.app` 内部二进制 —— 见 `references/platform-macos.md` |
| 辅助脚本 | PowerShell 版（`.ps1`） | Python 版（`.py`，仅用标准库） |
| MCP 层 | 完全一致（端口 8000，HTTP JSON-RPC） | 完全一致 |

## 仓库结构

```
SKILL.md                     # 路由表 + 法则库（G1-G17）+ 各类协议 —— 从这里开始读
references/
  capabilities/*.md          # 11 个分领域能力文档（设计规则 + 工具参数）
  dsl_syntax.md              # DSL 语法 R1-R27 及验证过的示例
  node_types.md              # 节点 type_id 参考（命名空间法则）
  ue_conventions.md          # 设计期知识（组件/碰撞/UI/中文语言环境）
  node_dict_extras.json      # 主字典中缺失、但经 PIE 验证的节点
  node_dictionary_merged.json# 1665 个节点的引擎字典（可检索，不建议通读）
  platform-macos.md          # macOS 环境对应说明
  few_shots.md               # 行为案例（该问/该拒绝/各类门禁）
  history/                   # 测试成果 + 一个真实故障案例复盘
  templates/                 # 17 个验证过的工作流模板（要改着用，别照抄）
scripts/
  ue_connect.py              # 一键连通性（check/launch/wait/all）
  mcp_call.py / .ps1         # MCP HTTP 调用器（参数走文件，免去转义地狱）
  search_node_dict.py / .ps1 # 离线节点/引脚检索
  refresh_schemas.py / .ps1  # schema 漂移守卫（离线交叉校验 + --live）
  bp_template.py, verify_bp.py, import_asset.ps1 ...
```

## 语言

技能内容以英文为主，同时保留中文触发词（该技能诞生于中英混合的工作流——中文用户可以直接说「连不上」「帮我打开项目」这类原生说法）。欢迎使用任意一种语言贡献。

## 贡献

本技能是自维护的：凡是被诊断并验证过的失败，都会被沉淀为法则条目（见 SKILL.md 的 *Self-Maintenance Protocol*）。最有价值的 PR 是来自真实 PIE 运行的 `[VERIFIED]` 经验。

## 许可

[MIT](LICENSE) —— 覆盖知识库、脚本与模板。Unreal Engine 是 Epic Games, Inc. 的商标；本项目与 Epic Games 无隶属关系，也未获其背书。

# 内网迁移与 AI 工具接管手册

> 目的：把当前外网开发上下文完整、可验证地交给内网环境和新的 vibe coding 工具/模型。
> 交接基线：Git `main` 分支，提交 `341e5c0 Hydrate runs in lifecycle evaluation history`。

## 1. 一页结论

- **运行时不依赖外部大模型**：当前算法内核、平台后端和前端均没有调用 OpenAI、Langfuse SDK 模型、
  embedding 服务或生成式判官。
- **embedding 为离线可选组件（E2 起）**：意图视图可选用本地 `BAAI/bge-m3` 编码器
  （纯本地推理、不触网、权重独立分发，见 §9.1 与 `DEPLOYMENT.md` §3.12）；
  不启用时保持"轨迹自带 embedding 字段"行为。除此之外不使用任何在线向量模型。
- **切换 vibe coding 工具/模型不影响业务结果**：切换的是“开发助手”，不是系统内的业务模型。
  只要代码提交一致，平台行为和分数应一致。
- **内网首版运行形态**：一套平台对接一个 Langfuse v4 实例；推荐 `selfhosted-v4` profile。
- **迁移核心资产是代码、契约、文档和测试**，不是对话历史。新工具必须从 `AGENTS.md` 开始。

## 2. 新工具接管顺序

内网 AI 工具第一次进入仓库时，应按以下顺序建立上下文：

1. 读根目录 `AGENTS.md`：工程纪律、禁区、命令、模块地图。
2. 读本文：迁移状态、验收命令、上下文快照。
3. 读 `platform/DESIGN.md`：已拍定架构与被否决方案，尤其是一 Project 一本体、噪声不治理、
   v3 延后等决策。
4. 读 `platform/DEPLOYMENT.md`：版本、数据库、profile、发布包和验收记录。
5. 读 `platform/USAGE_GUIDE.md`：业务方操作流和当前能力边界。
6. 按改动模块定位 `platform/app/` 对应文件与 `platform/tests/` 对应测试。

建议给新工具的首个提示词：

```text
你是本仓库的接手开发助手。请先阅读 AGENTS.md、platform/INTRANET_HANDOFF.md、
platform/DESIGN.md、platform/DEPLOYMENT.md 和 platform/USAGE_GUIDE.md。
遵守其中的硬性规则，不要引入生成式判官或未记录的模型依赖。
开始任务前先复述你的理解、改动范围和将运行的验证命令。
```

## 3. 当前工程快照

| 项 | 当前状态 |
|---|---|
| Git 基线 | `main`，`341e5c0` |
| 后端 | FastAPI `0.115.6`，Uvicorn `0.34.0`，PyYAML `6.0.3`；E2 起另钉推理包：torch `2.14.0`、sentence-transformers `6.3.0`、transformers `5.24.1` 等（`requirements.txt`，仅平台层，kernel 纯标准库） |
| 前端 | Node `>=24 <25`，Vite `6.0.7`，React `18.3.1`，TypeScript `5.7.2`，ECharts `5.6.0` |
| 存储 | SQLite，`platform/contracts/schema.sql`；当前契约：23 张表，schema v10；另有可弃置 embedding 缓存 `platform/var/embedding-cache.db` |
| Langfuse | 首版只支持 Cloud v4 与自托管 v4；自托管 v3 延后 |
| 外部模型 | 无 LLM；**E2 起可选离线 embedding**：`BAAI/bge-m3`（revision `5617a9f6…`，2.27GB 权重在 `platform/var/models/bge-m3/`，不入库，资产清单 `platform/config/model_assets.json`） |
| 生产入口 | 后端单进程托管 `frontend/dist`，`/api/` 与 SPA 路由同端口 |
| 基准 | `bench/` 全链路可复现；完整矩阵约 15 分钟量级 |

模块入口：

- API 服务：`platform/app/service.py`
- CLI：`platform/app/cli.py`
- 存储与 schema 迁移：`platform/app/store.py`，`platform/contracts/schema.sql`
- Langfuse 源：`platform/app/langfuse_source.py`
- Scores 写回：`platform/app/langfuse_scores.py`
- 人工复核队列：`platform/app/langfuse_reviews.py`
- 生命周期与调度：`platform/app/lifecycle.py`，`platform/app/scheduler.py`
- 告警决策：`platform/app/alerts.py`
- 前端：`frontend/src/`

## 4. 代码迁移方式

优先按以下顺序迁移，任选一种，不要混用手工拷贝。

### 方式 A：Git bundle

外网机器：

```powershell
git bundle create traj-engine.bundle main
git hash-object traj-engine.bundle
```

内网机器：

```powershell
git clone traj-engine.bundle traj-engine
cd traj-engine
git checkout main
git log -1 --oneline
```

验收目标：能看到 `341e5c0 Hydrate runs in lifecycle evaluation history`。

### 方式 B：发布包

```powershell
npm --prefix frontend run build
python -m unittest discover -s platform/tests -v
python -m platform.app.cli release --version 0.1.0-intranet
python -m platform.app.cli release-verify --package platform/var/releases/traj-engine-0.1.0-intranet.zip
```

发布包不包含 `.env`、`platform/var/`、`node_modules/`、真实租户档案或 240 MB 基准数据。
若需要基准数据，必须通过 Git 迁移或另行建立受控数据资产。

## 5. 内网依赖准备

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | `3.11.x` | 内网镜像或离线 wheel 均可 |
| FastAPI | `0.115.6` | `requirements.txt` 固定 |
| Uvicorn | `0.34.0` | `requirements.txt` 固定 |
| PyYAML | `6.0.3` | `requirements.txt` 固定 |
| torch | `2.14.0` | 仅启用意图编码器时需要；CPU wheel |
| sentence-transformers | `6.3.0` | 同上；配套 `transformers 5.24.1`、`tokenizers 0.23.3`、`safetensors 0.8.0`、`huggingface-hub 2.5.0`、`numpy 2.4.6`、`scipy 1.17.1`、`scikit-learn 1.9.1`（均钉版） |
| bge-m3 离线模型包 | revision `5617a9f6…`，2.14 GiB | 独立分发，不入库；SHA-256 清单在 `platform/config/model_assets.json` |
| Node.js | `>=24 <25` | 用于构建前端 |
| npm | 随 Node.js | 需能访问内网 npm 镜像 |
| SQLite | Python 内置 | 不单独引入数据库服务 |
| Langfuse | v4 自托管 | 外部组件，不属于本仓库发布包 |

离线安装建议：

```powershell
python -m pip install -r requirements.txt
npm --prefix frontend ci
```

离线模型包准备与校验（启用意图编码器时必做）：

```powershell
# 1) 将模型包整体拷贝到部署机（路径任意，10 个文件，2.14 GiB）
# 2) 启动前逐文件校验 SHA-256（退出码 0 才允许启动）
python -m platform.scripts.verify_model_assets --root <模型包目录>
# 3) 启动时经环境变量启用并指向包目录
$env:TRAJ_INTENT_ENCODER = "bge-m3"
$env:TRAJ_MODEL_ROOT = "<模型包目录>"   # 缺省为 platform/var/models/bge-m3
```

校验器输出资产指纹（当前 `e06d2e2362d5bb75`），与 Run 溯源记录一致即为正确包；
缺失或 hash 不符退出码 1 并列出问题文件。即使跳过人工校验，服务启动门禁也会
拦截（启动失败并输出修复指引），不会带病运行。完整资源与回滚矩阵见
`DEPLOYMENT.md` §3.13。

如果内网不能访问公网 PyPI/npm，需要提前准备内部镜像或离线包，并把实际镜像地址记录到
`platform/DEPLOYMENT.md`，不要写入凭据。

## 6. 配置与凭据迁移

### 6.1 禁止迁移项

- `.env`
- Langfuse public key / secret key
- `platform/var/` 中的数据库、运行数据、复核结果和发布包
- 任何租户真实档案

生产凭据应由内网管理员在内网 secret 系统或部署机 `.env` 中重新配置。该文件已 gitignore。

### 6.2 必须迁移项

- Git 代码与 `frontend/package-lock.json`
- `platform/contracts/` 契约
- `platform/config/` 配置模板
- `README.md` 与 `platform/*.md` 文档
- 测试与 CI workflow

### 6.3 内网 profile

默认 profile 为 `selfhosted-v4`，基础地址由 `--base-url` 或环境变量覆盖：

```powershell
python -m platform.app.cli run `
  --profile selfhosted-v4 `
  --base-url http://langfuse.internal `
  --db platform/var/traj-engine.db `
  --host 127.0.0.1 `
  --port 8000
```

如内网 Langfuse 域名不是 `http://langfuse.internal`，只改启动参数或内网环境变量，不把 URL 写死进业务代码。

## 7. 内网初始化与验收

在干净迁移目录执行：

```powershell
python -m platform.app.cli init --db platform/var/traj-engine.db
npm --prefix frontend run build
python -m platform.app.cli run --profile selfhosted-v4 --base-url http://langfuse.internal --db platform/var/traj-engine.db --port 8000
python -m platform.app.cli smoke --profile selfhosted-v4 --base-url http://127.0.0.1:8000
```

再执行完整门禁：

```powershell
python -m compileall -q platform
python -m unittest discover -s platform/tests -v
npm --prefix frontend run build
```

人工检查：

1. `http://127.0.0.1:8000/` 能打开生产控制台。
2. `/api/v1/health` 返回正常。
3. Langfuse 连通性、版本和 profile 显示为内网 v4，而不是 Cloud。
4. 新建/导入租户后，轨迹读取、Run、Scores 写回、复核队列同步均可走通。
5. 注册生命周期后，调度器进程保持运行，R1/R2 历史能持久化。
6. 启用意图编码器时：启动前 `verify_model_assets` 退出码 0；冷启动至健康
   约 45s（含权重校验与加载，实测 44.5s）；故意移除任一权重文件后启动必须
   失败且错误信息含修复指引（验收红线，不得跳过）。

## 8. 数据迁移

- 首次内网验证建议使用**空 SQLite 数据库**，通过控制台重新接入内网 Langfuse Project。
- 不要把外网 `platform/var/traj-engine.db` 直接拷到内网作为生产库；其中包含外网运行数据、
  租户凭据和历史 Run。
- 如确需迁移历史 Run，必须单独立项做字段级导出/导入方案，并明确：
  - `run_id`、本体版本、structure version、`code_hash` 保留；
  - 凭据字段剔除；
  - 迁移前后表数量、行数、关键哈希对账；
  - 历史分数只读，不允许在新环境重写旧结果。

## 9. 模型与工具切换规则

### 9.1 当前状态

- **业务模型**：聚类、异常识别、打分、扣分归因全部由仓库内确定性代码完成；无 LLM、无在线服务调用。
- **开发模型**：Codex 或后续内网 vibe coding 工具只是开发助手，不进入生产运行链路。
- **embedding**：**已接入（E2，2026-11-27）**——离线 `BAAI/bge-m3`（dense，1024 维），
  权重为独立离线模型包（`platform/var/models/bge-m3/`，2.27GB，不入库），
  资产清单与部署验收见 `platform/config/model_assets.json` 与 `DEPLOYMENT.md` §3.12；
  由 `TRAJ_INTENT_ENCODER=bge-m3` 启用，不启用时保持"轨迹自带 embedding 字段"行为。
  它是**可选增强**而非新增外部服务：纯本地推理，不触网。

### 9.2 切换验证

切换工具后先做不改代码的只读任务：

1. 要求新工具总结工程目标、硬性纪律和当前模块。
2. 要求它复述 R1/R2、校准、告警和复核链路。
3. 要求它列出准备修改的文件和验证命令。

如果总结出现以下错误，说明上下文未接管成功：

- 认为系统需要外部 LLM 判官；
- 认为 embedding 来自在线服务或需要触网（E2 起为离线 bge-m3 本地推理，可选启用）；
- 想恢复 mixed-agent project 检测或 `foreign_ratio`；
- 想绕过测试直接改内核；
- 把 Langfuse Cloud key 写入仓库或本体 YAML。

### 9.3 未来引入模型时

> 本节清单的首个完整实例：**bge-m3（E2，2026-11-27）**——全部记录项落实在
> `platform/config/model_assets.json`（版本/哈希/维度/截断/归一化/后端）、
> `DEPLOYMENT.md` §3.12（获取与校验、缓存、资源实测、回滚）与
> `DESIGN.md` §7.9（对 `code_hash` / 历史 Run 可比性的影响论证）。

任何新增模型资产必须补齐以下记录，缺一项不得合入：

- 用途（embedding、分类、辅助标注等）
- 供应商与部署位置
- 精确模型名、版本、参数量、权重文件哈希
- 输入格式、截断规则、维度、归一化规则
- 批量大小、超时、缓存和并发
- 离线获取与校验方式
- 基准结果与失败模式
- 对 `code_hash`、`structure_version`、历史 Run 可比性的影响
- 回滚方案

## 10. 常用排障入口

| 现象 | 优先检查 |
|---|---|
| 服务打不开 | 进程、端口、`--profile`、启动日志 |
| Langfuse 未核对 | profile 基础地址、内网 DNS、key 权限、health 响应 |
| Run 无数据 | 时间窗、Langfuse Project 轨迹量、trace source、配额 |
| 调度未执行 | 调度注册状态、线程存活、评估历史、服务是否被重启 |
| R2 结果不可比 | structure version、训练样本、抽样策略、本体版本 |
| 告警/复核异常 | `platform/app/alerts.py`、`langfuse_reviews.py` 与对应测试 |
| 前端空白 | `frontend/dist` 是否存在、静态路由、浏览器 console |

## 11. 交接确认表

- [ ] 内网仓库可检出 `341e5c0` 或更新的已验证提交。
- [ ] Python 3.11 与 pinned 依赖安装完成。
- [ ] Node 24 与 `frontend/package-lock.json` 构建完成。
- [ ] 空数据库初始化成功。
- [ ] `selfhosted-v4` 指向内网 Langfuse v4。
- [ ] Health、冒烟、平台测试、前端构建全部通过。
- [ ] 凭据只存在于内网 secret / `.env`。
- [ ] 新 AI 工具已阅读并复述 `AGENTS.md` 和本文。
- [ ] 后续开发继续把部署、依赖、模型变化同步记录到 `platform/DEPLOYMENT.md`。

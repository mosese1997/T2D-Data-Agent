# OpenSandbox 1.2.0 实测报告（t2d 代码沙箱选型探测）

- 日期：2026-10-30
- 环境：ecs-litellm-test（Linux x86_64，Docker 26.1.3），探测 venv `/root/rappi_t2d/var/probe-venv`
- 版本：`opensandbox` SDK 1.2.0 + `opensandbox-server` 1.2.0（pip 实测确认）
- 探测产物：
  - 配置：`/root/rappi_t2d/var/probe-scripts/opensandbox-config.toml`
  - 脚本：`opensandbox_probe.py`（生命周期/资源/网络/隔离）、`opensandbox_probe2.py`（修正轮）、`opensandbox_probe3.py`（server kill 残留）、`opensandbox_probe4.py`（取消）
  - 结果 JSON：`opensandbox_probe_results.json`、`opensandbox_probe2_results.json`
  - server 日志：`server.log`、`server2.log`
- 结论先行：**满足 t2d 全部沙箱需求，可直接用 SDK + 本地 server，仅需一层薄适配**（默认网络不隔离、必须每次请求显式传 deny 策略与资源参数，详见文末接入建议）。

## 1. Server 启动与配置

入口：venv `bin/opensandbox-server`（`opensandbox_server.cli:main`）。

```bash
cd /root/rappi_t2d/var/probe-scripts
opensandbox-server init-config ./opensandbox-config.toml --example docker   # 官方示例配置
# 编辑后启动：
opensandbox-server --config ./opensandbox-config.toml
```

健康检查：`GET /health` → `{"status":"healthy"}`，`GET /version` → `{"version":"1.2.0"}`（无需鉴权）。

### 实际使用的配置（相对示例的改动已标注）

```toml
[server]
host = "127.0.0.1"
port = 8003                      # 改动：示例默认 8080，本机 8080 留给 Nginx（t2d 端口约定 8003）
max_sandbox_timeout_seconds = 86400   # 沙箱生命周期 TTL 上限（秒）
api_key = "t2d-probe-key-2026"   # 改动：启用鉴权。留空则启动需交互确认或 OPENSANDBOX_INSECURE_SERVER=YES

[proxy]
resolve_internal = true          # 反代走沙箱容器桥接 IP

[log]
level = "INFO"

[runtime]
type = "docker"
execd_image = "opensandbox/execd:v1.1.0"   # execd 二进制从该镜像抽取后注入沙箱容器

[storage]
allowed_host_paths = []          # 宿主路径 bind mount 白名单；空=允许全部（生产应收紧）
volume_default_size = "1Gi"      # 仅 K8s PVC 用

[store]
type = "sqlite"
path = "/root/rappi_t2d/var/probe-scripts/opensandbox.db"   # 改动：不放家目录

[docker]
network_mode = "bridge"          # 沙箱容器网络；egress sidecar + networkPolicy 必须 bridge
port_range_min = 40000           # 沙箱端口发布范围（每沙箱 2-3 个宿主端口）
port_range_max = 60000
publish_host = "127.0.0.1"       # 改动：示例注释掉；收紧到本机回环，不暴露公网接口
drop_capabilities = ["AUDIT_WRITE","MKNOD","NET_ADMIN","NET_RAW","SYS_ADMIN","SYS_MODULE","SYS_PTRACE","SYS_TIME","SYS_TTY_CONFIG"]
no_new_privileges = true
apparmor_profile = ""
pids_limit = 4096                # 防 fork 炸弹；null 可关闭
seccomp_profile = ""             # 空=Docker 默认
# sandbox_env = {...} / sandbox_binds = [...]   # 可选：全局注入 env / 宿主 bind mount（默认无）

[ingress]
mode = "direct"

[egress]
image = "opensandbox/egress:v1.1.7"   # networkPolicy 请求时才起的 sidecar 镜像
mode = "dns"                    # 可选 "dns+nft"（nftables 强制，更强）
readiness_timeout_seconds = 30.0

[renew_intent]
enabled = false
```

### 与沙箱相关的配置项清单（真实存在，来自 config.py / 实测）

| 配置 | 作用 | 默认 |
|---|---|---|
| `server.api_key` | API 鉴权（header `OPEN-SANDBOX-API-KEY`） | 空（需显式确认才能起） |
| `server.max_sandbox_timeout_seconds` | 沙箱 TTL 上限 | 86400 |
| `docker.network_mode` | host/bridge/none/自定义网络 | bridge |
| `docker.port_range_min/max` | 桥接模式宿主端口池 | 40000–60000 |
| `docker.publish_host` | 端口发布到的宿主地址 | 0.0.0.0（建议 127.0.0.1） |
| `docker.drop_capabilities` / `no_new_privileges` / `pids_limit` / `seccomp_profile` / `apparmor_profile` | 容器加固 | 见上 |
| `docker.sandbox_env` / `sandbox_binds` | 全局 env / 宿主挂载注入 | 无 |
| `storage.allowed_host_paths` | bind mount 白名单 | 空=全允许 |
| `egress.mode` | dns / dns+nft | dns |
| **资源限制（CPU/内存）不在 server 配置里** | 由 SDK create 请求的 `resource` 字典逐沙箱传入，server 转成 docker `mem_limit`/`nano_cpus`（`container_ops.py:364-428` 实读确认） | SDK 侧默认 `{"cpu":"1","memory":"2Gi"}` |

鉴权实测：无 key / 错误 key 调 `POST /api/v1/sandboxes` → **401**；正确 key → 正常。

## 2. SDK 生命周期实测（probe.py 第 1 节）

`Sandbox.create("python:3.12-slim", resource={"cpu":"1","memory":"1Gi"}, timeout=timedelta(minutes=10))` → `commands.run` → `files.write_files` → run 脚本 → `files.read_file` → `destroy`。

| 步骤 | 实测耗时 | 结果 |
|---|---|---|
| create（冷，首次，含 execd 注入） | **5.08 s** | ok |
| create（暖，第 2/3 次） | **2.77 s / 2.0 s** | ok |
| `commands.run('python3 -c "print(6*7)"')` | 1.02 s（含约 1s 固定开销） | stdout `42`，exit 0 |
| `files.write_files`（1 个小文件） | 0.01 s | ok |
| run 写入的脚本 | 1.07 s | `{"answer": 42, "path_ok": true}` |
| `files.read_file` 回读 | <0.01 s | 内容一致 |
| `destroy` | 1.35 s | ok |
| destroy 后 `docker ps -a` 残留 | — | **0 个容器**（label `opensandbox.io/id` 过滤） |

运行中容器 `docker inspect` 实测：
- `Mounts: []` — **无任何宿主目录挂载**
- `Memory: 1073741824`（1 GiB）、`NanoCpus: 1000000000`（1 vCPU）— **resource 字典真实生效**
- `PidsLimit: 4096`、`CapDrop` 9 项、`SecurityOpt: ["no-new-privileges=true"]`
- `NetworkMode: bridge`，端口只发布在 `127.0.0.1`（44772=execd，8080=沙箱内服务）

## 3. 资源限制实测（probe.py 第 2 节 + probe2）

沙箱以 `resource={"cpu":"1","memory":"1Gi"}` 创建（t2d 默认值）。

- **内存超限 OOM**：沙箱内 `bytearray(2*1024**3)`（2 GiB）→ 命令 1.17 s 内被杀，`exit_code=-1`，error `signal: killed`；宿主 `free -m` 无波动（31 GB 总内存占用 4.5 GB 不变）；**沙箱本身存活**，后续命令正常。→ cgroup mem_limit 生效，OOM 只杀进程不杀容器。
- **CPU 限制**：2 个 burn 线程跑 4 s 墙钟，`process_time=3.99 s`，比值 **1.0** → 严格压在 1 vCPU（无限制时应接近 2.0）。
- **执行超时**：`RunCommandOpts(timeout=timedelta(seconds=5))` 跑 `sleep 60` → 6.0 s 墙钟时命令被杀（`signal: killed`，exit -1），**沙箱仍可用**（后续命令正常返回）。执行超时是**逐命令**参数，省略则不设限；与沙箱 TTL（`timeout`，create 参数，server 校验 **最小 60 s**、上限 `max_sandbox_timeout_seconds`）是两层独立机制。
- **取消**（probe4）：`opts=RunCommandOpts(background=True)` 起 `sleep 300` → `commands.interrupt(execution_id)` → 2.06 s 后 `running: False, exit_code: -1, error: "signal: terminated"`。后台命令状态可用 `get_command_status` 轮询。

## 4. 网络隔离实测（probe2 第 3 节）

沙箱内用 `urllib.request`（HEAD，8 s 超时）实测三个目标：`https://pypi.org/simple/`、宿主网关 `http://172.17.0.1:4000`（本机 LiteLLM）、裸 IP `http://93.184.216.34/`。

| 策略 | pypi.org | 172.17.0.1:4000 | 裸 IP |
|---|---|---|---|
| **默认（不传 network_policy）** | REACHABLE 200 | REACHABLE 200 | REACHABLE 200 |
| `NetworkPolicy(default_action="deny")` | BLOCKED（DNS 解析失败） | BLOCKED | BLOCKED |

- **默认策略 = 完全放通出网**（bridge 网络）。t2d "任务运行默认禁止互联网访问"**必须每次 create 显式传 `NetworkPolicy(default_action="deny")`**，server 配置里没有全局默认策略项（config.py 实读确认）。
- deny 时 server 会额外起一个 egress sidecar 容器（`opensandbox/egress:v1.1.7`，label `opensandbox.io/egress-sidecar-for=<sandbox_id>`，与沙箱同 netns）。deny 模式下连宿主网关与裸 IP 也被拦（实测均 `Name or service not known`）。
- `egress.mode` 可配 `"dns+nft"`（nftables 强制），比默认 `"dns"` 更强，生产建议切换；本次实测在 `dns` 模式完成。
- 规则可细化：`NetworkRule(action="allow"/"deny", target="FQDN|*.wildcard|IP|CIDR", ports=[...])`，按序求值——t2d 若将来要放行内网某地址可用。

## 5. 文件与凭据边界实测（probe.py 第 4 节）

- 沙箱 A 写 `/tmp/t2d_secret.txt`（mode 600）→ destroy → 新建沙箱 B 读取 → `No such file or directory`。**不同任务不复用遗留文件，确认隔离**。
- 两个沙箱 `docker inspect` 的 `Mounts` 均为 `[]` — **无宿主目录挂载，无凭据泄露通道**。
- 凭据面：默认无任何 env/挂载注入；`docker.sandbox_env`/`sandbox_binds` 是全局注入点（保持注释掉即可）；`env` 是 create 的逐沙箱参数，可用来传短期 token。SDK 另有 Credential Vault（credential_proxy）能力，本次未启用。

## 6. 异常清理实测（probe3）

- 创建一个 30 分钟 TTL 的沙箱（含 egress sidecar），`kill -9` server 进程：
  - **沙箱容器 + sidecar 继续运行**（Docker 层面不受 server 存活影响）。
  - 重启 server 后日志：`Restored expiration timers for 1 sandbox(es).` — **启动时按容器 label 重建 TTL 定时器（收养），不杀旧容器**；已过期的会在启动时立即终止，孤儿 sidecar 会被清理（`docker_service.py:_restore_existing_sandboxes` 实读确认）。
  - 即：server crash 不会导致容器永久泄漏（TTL 兜底），但也不会立即回收。
- 沙箱 TTL 自动回收实测：60 s TTL 的沙箱不调用 destroy，**恰好 60 s 后容器被 server 自动删除**（`shutdown_policy` 默认 Delete）。
- 手动清理命令（只动 opensandbox 标签的容器，不影响本机其他容器）：

```bash
# 查看所有 opensandbox 沙箱容器
docker ps -a --filter "label=opensandbox.io/id"
# 强删全部沙箱容器（含已停止）
docker rm -f $(docker ps -aq --filter "label=opensandbox.io/id")
# 强删全部 egress sidecar
docker rm -f $(docker ps -aq --filter "label=opensandbox.io/egress-sidecar-for")
# 单个沙箱
docker rm -f sandbox-<sandbox_id> sandbox-egress-<sandbox_id>
```

## 7. 能力矩阵

| t2d 需求（§15/§11） | OpenSandbox 1.2.0 实测 | 结论 |
|---|---|---|
| Docker Runtime 动态创建 Python 沙箱 | `runtime.type="docker"`，任意镜像（python:3.12-slim 实测），execd 自动注入 | ✅ |
| 执行代码并返回结果/文件 | `commands.run`（stdout/stderr/exit_code/error）+ `files.write_files/read_file/read_bytes` | ✅ |
| 1 vCPU / 1 GB 可配置 | create 参数 `resource={"cpu","memory"}` → docker `NanoCpus`/`Memory`，inspect 与压测双重确认 | ✅（逐请求传参） |
| 单沙箱执行 120 s 超时 | 逐命令 `RunCommandOpts(timeout=...)`，任意秒数；超时杀进程不杀沙箱 | ✅ |
| 取消 | `commands.interrupt(execution_id)`，实测 ~2 s 终止 | ✅ |
| 默认禁互联网 | **默认放通**；须显式 `NetworkPolicy(default_action="deny")`，实测全拦（含宿主网关/裸 IP） | ⚠️ 需适配层显式传参 |
| 不注入长期凭据 | 默认零挂载零注入（Mounts=[]），env 逐沙箱 | ✅ |
| 受控文件交换 | write_files/read_file API，实测往返一致 | ✅ |
| 超时/取消/异常后清理 | destroy 无残留；TTL 自动回收实测 60 s 精确；server crash 后容器被重启收养+TTL 兜底 | ✅ |
| 任务间文件隔离 | 前后沙箱互不可见，无共享卷 | ✅ |
| 并发 1 | server 支持多沙箱（端口池 40000-60000，约百级并发）；t2d 串行使用无压力 | ✅ |
| 鉴权 | `server.api_key` + header `OPEN-SANDBOX-API-KEY`，401 实测 | ✅ |
| 冷启动延迟 | 冷 5.1 s / 暖 2.0-2.8 s；每命令固定 ~1 s 开销 | ✅ 可接受 |

## 8. t2d 接入建议

**直接用 SDK + 本地 server（8003），加一层薄适配**（`packages/` 下新建 sandbox_adapter 或并入 worker），适配层必须补：

1. **默认安全参数固化**（防漏传）：封装 `run_isolated(code, files, timeout_s=120)`，内部固定
   `resource={"cpu":"1","memory":"1Gi"}`、`network_policy=NetworkPolicy(default_action="deny")`、`timeout=timedelta(minutes=10)`（沙箱 TTL 兜底）、每命令 `RunCommandOpts(timeout=timedelta(seconds=120))`。资源上限可从 t2d 配置读。
2. **每任务一沙箱一 destroy**：finally 块 `await sandbox.destroy()`；TTL 作为泄漏兜底（≥60 s，server 强制最小值）。
3. **结果回传**：分析脚本约定把结果 JSON 写到固定路径（如 `/tmp/t2d_result.json` + 产物文件），适配层 `read_file`/`read_bytes` 取回；stdout 作为日志。
4. **部署**：server 以 systemd/后台进程跑在 8003（127.0.0.1），配置沿用本探测文件（api_key 换正式值进 `.env`）；`publish_host="127.0.0.1"`、`storage.allowed_host_paths` 收紧为空数组语义上保持不挂载。
5. 可选增强：`egress.mode="dns+nft"`；预拉 `python:3.12-slim` + 预装 pandas/matplotlib 打成 t2d 专用镜像（消除 pip 安装需求——沙箱禁网后不能现场装包，**依赖必须烧进镜像**）。
6. 并发 1：worker 串行调用即可；若未来并发，注意每沙箱占 2-3 个宿主端口与 ~1 GB 内存。

### 已知注意点
- 沙箱 TTL 最小 60 s（server 422 校验），不能创建短于 1 分钟的沙箱——对"执行完即销毁"无影响（主动 destroy 即可）。
- 每条命令有 ~1 s 固定开销（execd HTTP 往返），批量小命令建议合并成一个脚本一次 run。
- 禁网沙箱内不能 pip install；所有 Python 依赖需在镜像内。
- server crash 时运行中的沙箱会存活到 TTL；适配层无需额外处理，但监控可加 `docker ps --filter label=opensandbox.io/id` 巡检。

## 9. 探测后清理状态

- server 进程已停止；`docker ps -a` 中 label `opensandbox.io/id` / `opensandbox.io/egress-sidecar-for` 的容器数为 0。
- 保留镜像：`python:3.12-slim`、`opensandbox/execd:v1.1.0`、`opensandbox/egress:v1.1.7`（共约 200 MB，t2d 直接复用）。
- 本机其他容器/卷/镜像未做任何改动。

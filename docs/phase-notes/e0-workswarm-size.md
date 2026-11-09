# E0 探测 3：workswarm 依赖体积 — ⚠️ 可行但重（1.9GB）

- 独立 venv 安装 workswarm（含依赖）：**1.9GB**（现有 probe-venv 实测 1.8GB，一致）
- 对比：当前 worker 镜像 site-packages 仅 115MB——装 workswarm 会让 worker 镜像从 ~215MB 膨胀到 **~2.1GB**
- google-adk 全家桶是体积主因（传递依赖）

## E4 实施建议（三选一，开工前定）
1. **独立 venv in-image**（最直接）：worker 镜像加一层 venv 安装 workswarm，运行时 sys.path 切换——镜像 2.1GB，演示机磁盘可承受（一次性构建成本）
2. **sidecar 进程**：workswarm 装在宿主/独立容器，worker 经 IPC 调用——镜像小但多一层进程管理复杂度
3. **按需挂载**：镜像不含 workswarm，运行时检测 var/probe-venv 存在则启用 swarmflow——镜像最小，部署文档多一个前置步骤

**结论：GO（方案 1 为默认建议）**——体积是成本不是阻塞；boundaries.md 记录镜像尺寸边界。

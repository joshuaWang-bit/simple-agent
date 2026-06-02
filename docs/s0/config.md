# S0 配置系统

## CLI 入口先读配置

用户执行 `sagent ping` 后，最先跑起来的是 `cli/main.py`。它只做三件事：**解析参数、读取配置、把控制权交给命令**。

```python
# cli/main.py
def main() -> None:
    parser = argparse.ArgumentParser(prog="sagent", description="SimpleAgent CLI")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("ping", help="Ping the core daemon")

    args = parser.parse_args()

    if args.version:
        cmd_version()
        return

    config = get_config()
    setup_logging(config)

    if args.command == "ping":
        cmd_ping(config)
    else:
        parser.print_help()
        sys.exit(1)
```

为什么 CLI 一进来就要读配置？因为 `ping` 需要知道 daemon 监听在哪个 host 和 port 上。s0 的默认值是 `127.0.0.1:7437`，但测试、开发和未来部署都可能覆盖它。

## 配置来源按四级优先级合并

```
内建默认值 → ~/.sagent/config.toml → .env → SAGENT_* 环境变量
```

对应代码在 `core/config.py`：

```python
def get_config() -> AgentConfig:
    config = AgentConfig()

    load_dotenv(".env", override=False)

    config_path = Path(
        os.environ.get("SAGENT_CONFIG", _DEFAULT_CONFIG_PATH)
    ).expanduser()
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(config, data)

    _apply_env(config)
    return config
```

### 加载顺序的设计理由

`load_dotenv(".env", override=False)` 要放在读 TOML 之前，因为 `.env` 里可以设置 `SAGENT_CONFIG` 来改变 TOML 文件路径。同时 `override=False` 保证 shell 里已经导出的环境变量不会被 `.env` 覆盖。

> ⚠️ 这不是随意的加载顺序。如果先读 `~/.sagent/config.toml`，再加载 `.env`，那么 `.env` 里的 `SAGENT_CONFIG` 永远不会影响配置文件路径；如果让 `.env` 覆盖系统环境变量，部署环境里显式传入的 `SAGENT_PORT` 又会被本地文件悄悄改掉。

## 配置模型

```python
class AgentConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7437
    log_level: str = "INFO"

    model_config = {"extra": "ignore"}
```

`extra = "ignore"` 保证配置文件中可以包含后续阶段才会用到的字段，而不会在 s0 就触发校验错误。

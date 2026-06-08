"""
memcore-cloud 统一配置加载器
所有源码必须从此模块读取路径配置，禁止硬编码用户私有绝对路径。
"""
import json, os, re

_CONFIG = None
_CONFIG_ENV = None

def _script_base():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _root_config_path(root):
    return os.path.join(root, "config", "memcore.json")

def _valid_memcore_root(root):
    return bool(root) and os.path.isfile(_root_config_path(root))

def _uninitialized_memcore_root(root):
    return bool(root) and not os.path.exists(root)

def _project_base():
    """返回项目根目录。只有包含 config/memcore.json 的 MEMCORE_ROOT 才可信。"""
    env_root = os.environ.get("MEMCORE_ROOT")
    if _valid_memcore_root(env_root):
        return env_root
    return _script_base()

def _load():
    global _CONFIG, _CONFIG_ENV
    env_signature = (
        os.environ.get("MEMCORE_ROOT"),
        os.environ.get("MEMCORE_CONFIG"),
    )
    if _CONFIG is not None and _CONFIG_ENV == env_signature:
        return _CONFIG

    project_base = _project_base()
    explicit_config = os.environ.get("MEMCORE_CONFIG")
    config_path = explicit_config or _root_config_path(project_base)
    with open(config_path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)

    env_root = os.environ.get("MEMCORE_ROOT")
    if explicit_config and env_root:
        base_dir = env_root
    elif _valid_memcore_root(env_root):
        base_dir = env_root
    elif _uninitialized_memcore_root(env_root):
        base_dir = env_root
    else:
        base_dir = raw.get("_base_dir") or project_base

    # 环境变量展开pattern: ${VAR:-default} 或 $VAR
    _ENV_PATTERN = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)')

    def _expand_env(s):
        def _repl(m):
            if m.group(1) is not None:
                var, default = m.group(1), m.group(2) or ''
                return os.environ.get(var) or default
            return os.environ.get(m.group(3)) or ''
        return _ENV_PATTERN.sub(_repl, s)

    resolved = {}
    for key, val in raw.items():
        if key.startswith("_"):
            continue
        elif isinstance(val, dict):
            resolved[key] = {}
            for k, v in val.items():
                if isinstance(v, str):
                    v = _expand_env(v) if "$" in v else v
                    if key == "paths":
                        if v.startswith("~"):
                            resolved[key][k] = os.path.expanduser(v)
                        elif not os.path.isabs(v):
                            resolved[key][k] = os.path.join(base_dir, v)
                        else:
                            resolved[key][k] = v
                    else:
                        resolved[key][k] = v
                else:
                    resolved[key][k] = v
        else:
            resolved[key] = val
    resolved["_base_dir"] = base_dir

    _CONFIG = resolved
    _CONFIG_ENV = env_signature
    return _CONFIG


def get(path, default=None):
    """按点路径读取配置，如 get('paths.base')"""
    cfg = _load()
    keys = path.split(".")
    val = cfg
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val

def base_path():
    return get("paths.base") or get("_base_dir") or _project_base()

def get_memcore_root():
    """获取memcore-cloud项目根目录，自动从config_loader位置推断。
    禁止在源码中硬编码用户私有绝对路径。"""
    return base_path()

def memory_root():
    return get("paths.memory") or os.path.join(_project_base(), "memory")

def openclaw_agents():
    v = get("paths.openclaw_agents")
    if v:
        return os.path.expanduser(v) if v.startswith("~") else v
    return os.path.expanduser("~/.openclaw/agents")

def openclaw_workspace():
    v = get("paths.openclaw_workspace")
    if v:
        return os.path.expanduser(v) if v.startswith("~") else v
    return None

def codex_sessions():
    v = get("paths.codex_sessions")
    if v:
        return os.path.expanduser(v) if v.startswith("~") else v
    return os.path.expanduser("~/.codex/sessions")

def codex_session_index():
    v = get("paths.codex_session_index")
    if v:
        return os.path.expanduser(v) if v.startswith("~") else v
    return os.path.expanduser("~/.codex/session_index.jsonl")

def zhiyi_root():
    return get("paths.zhiyi") or os.path.join(_project_base(), "zhiyi")

def alias_map():
    return get("paths.alias_map") or os.path.join(_project_base(), "config", "alias_map.json")

def model_config():
    return get("paths.model_config") or os.path.join(_project_base(), "config", "model_config.json")

def lancedb_v2_metadata():
    return get("paths.lancedb_v2_metadata") or os.path.join(_project_base(), "config", "lancedb_v2_metadata.json")

def experience_lancedb():
    return get("paths.experience_lancedb") or os.path.join(_project_base(), "experience_lancedb")

def checkpoint_file():
    return get("paths.checkpoint") or os.path.join(_project_base(), ".checkpoint")

def config_dir():
    return get("paths.config_dir") or os.path.join(_project_base(), "config")

def node_id():
    return get("nodes.current") or "local"

def raw_memory_subpath():
    node = node_id()
    return get("nodes.raw_memory_subpath") or f"{node}/openclaw/openclaw_session_jsonl"

def lancedb_table_v1():
    return get("experience.lancedb_table_v1") or "experiences"

def lancedb_table_v2():
    return get("experience.lancedb_table_v2") or "experiences_v2"

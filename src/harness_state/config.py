"""Gerenciamento de configuração local, segredos e túnel SSH automático do Harness."""

import os
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ConfigurationError(RuntimeError):
    """Erro disparado quando a configuração do Harness não existe ou está incompleta."""


class SecretsConfig(BaseModel):
    """Configuração do arquivo de segredos locais dos agentes.

    Attributes:
        env_file: Caminho para o arquivo `.env` de segredos locais.
    """

    env_file: str = ""


class SSHTunnelConfig(BaseModel):
    """Configuração do túnel SSH automático para o State Tracker (Redis).

    Attributes:
        enabled: Habilita o suporte a túnel SSH no modo local.
        auto_open_on_run: Abre automaticamente o túnel durante `harness spec run`.
        host: Hostname público ou bastion SSH.
        user: Usuário SSH para autenticação.
        port: Porta SSH do host bastion.
        local_bind_host: Endereço local de bind do túnel.
        local_bind_port: Porta local exposta pelo túnel.
        remote_target_host: IP interno do servidor Redis na rede privada.
        remote_target_port: Porta interna do Redis no container.
        connect_timeout_seconds: Timeout de conexão SSH em segundos.
    """

    enabled: bool = True
    auto_open_on_run: bool = True
    host: str = ""
    user: str = ""
    port: int = 0
    local_bind_host: str = ""
    local_bind_port: int = 0
    remote_target_host: str = ""
    remote_target_port: int = 0
    connect_timeout_seconds: int = 5


class RedisEndpointsConfig(BaseModel):
    """Endereços internos e externos do State Tracker (Redis).

    Attributes:
        internal_host: IP interno na rede privada da Cloud.
        internal_port: Porta interna do Redis.
        external_host: Host local exposto pelo túnel SSH na máquina do dev.
        external_port: Porta local exposta pelo túnel SSH.
        db: Índice do banco lógico no Redis.
    """

    internal_host: str = ""
    internal_port: int = 0
    external_host: str = ""
    external_port: int = 0
    db: int = 0


class ElasticsearchEndpointsConfig(BaseModel):
    """Endereços internos e externos do Elasticsearch para telemetria do Harness.

    Attributes:
        internal_url: URL interna direta na rede privada.
        external_url: URL pública HTTPS (Reverse Proxy) para máquinas locais.
        index: Nome do índice de telemetria dos sensores e do Gate.
    """

    internal_url: str = ""
    external_url: str = ""
    index: str = ""


class LLMEndpointsConfig(BaseModel):
    """Endereços internos e externos do servidor LLM.

    Attributes:
        internal_base_url: Endpoint interno na rede privada da Cloud.
        external_base_url: Endpoint público HTTPS para acesso externo.
        default_model: Modelo configurado para codificação autônoma.
        judge_model: Modelo utilizado pelo LLM-as-a-Judge (DeepEval).
    """

    internal_base_url: str = ""
    external_base_url: str = ""
    default_model: str = ""
    judge_model: str = ""


class SpecHubConfig(BaseModel):
    """Configuração de localização dos repositórios de governança SDD.

    Attributes:
        github_org: Organização padrão dos repositórios spoke.
        default_repo: Nome do repositório Spec-Hub (`owner/repo`).
        flywheel_repo: Nome do repositório do orquestrador (`owner/repo`).
        local_relative_path: Caminho relativo do Spec-Hub no workspace local.
    """

    github_org: str = ""
    default_repo: str = ""
    flywheel_repo: str = ""
    local_relative_path: str = ""


class LangfuseConfig(BaseModel):
    """Configuração dos endpoints e chaves públicas do Langfuse.

    Attributes:
        host: URL base da API do Langfuse.
        public_key: Chave pública da API do Langfuse.
    """

    host: str = "https://us.cloud.langfuse.com"
    public_key: str = ""


class HarnessLocalConfig(BaseModel):
    """Configuração unificada para execução local e híbrida dos agentes e sensores.

    Attributes:
        version: Versão do schema de configuração.
        secrets: Configuração do arquivo de segredos.
        ssh_tunnel: Parâmetros do túnel SSH para o Redis.
        redis: Endereços internos e externos do Redis.
        elasticsearch: Endereços internos e externos do Elasticsearch.
        llm: Endereços internos e externos do provedor de LLM.
        spec_hub: Parâmetros do repositório Spec-Hub e organização.
        langfuse: Endpoints e chave pública do Langfuse para observabilidade e prompts.
    """

    version: str = "1.0"
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    ssh_tunnel: SSHTunnelConfig = Field(default_factory=SSHTunnelConfig)
    redis: RedisEndpointsConfig = Field(default_factory=RedisEndpointsConfig)
    elasticsearch: ElasticsearchEndpointsConfig = Field(
        default_factory=ElasticsearchEndpointsConfig
    )
    llm: LLMEndpointsConfig = Field(default_factory=LLMEndpointsConfig)
    spec_hub: SpecHubConfig = Field(default_factory=SpecHubConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)

    def resolve_secrets_path(self) -> Path | None:
        """Expande `~` e retorna o `Path` absoluto do arquivo de segredos.

        Returns:
            Caminho resolvido para o arquivo de segredos ou None se não configurado.
        """
        if not self.secrets.env_file.strip():
            return None
        return Path(self.secrets.env_file).expanduser().resolve()

    def build_redis_url(self, use_internal: bool = False) -> str:
        """Constrói a URL de conexão Redis para a topologia selecionada.

        Args:
            use_internal: Se True, usa o host interno; senão, usa o túnel externo.

        Returns:
            String de conexão Redis formatada ou vazia se não configurada.
        """
        host = self.redis.internal_host if use_internal else self.redis.external_host
        port = self.redis.internal_port if use_internal else self.redis.external_port
        if not host or not port:
            return ""
        return f"redis://{host}:{port}/{self.redis.db}"

    def resolve_elasticsearch_url(self, use_internal: bool = False) -> str:
        """Retorna a URL base do Elasticsearch conforme a topologia ativa.

        Args:
            use_internal: Se True, retorna a URL interna configurada.

        Returns:
            URL base do Elasticsearch sem barra final.
        """
        url = (
            self.elasticsearch.internal_url
            if use_internal
            else self.elasticsearch.external_url
        )
        return url.rstrip("/")


@dataclass(slots=True)
class TunnelStatus:
    """Resultado da verificação ou abertura automática do túnel SSH.

    Attributes:
        active: Indica se a conexão com o Redis está disponível (via túnel ou rede).
        opened_now: True se o processo SSH foi disparado nesta chamada.
        reason: Código descritivo do estado (`already_listening`, `opened_ssh_tunnel`).
        command: Comando SSH executado, quando aplicável.
    """

    active: bool
    opened_now: bool
    reason: str
    command: str = ""


def get_default_user_config_path() -> Path:
    """Retorna o caminho padrão global do arquivo de configuração local do usuário.

    Returns:
        Path apontando para `~/.config/harness/config.yaml`.
    """
    return Path.home() / ".config" / "harness" / "config.yaml"


def is_tcp_port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    """Verifica rapidamente se uma porta TCP está acessível e aceitando conexões.

    Args:
        host: Endereço IP ou hostname a testar.
        port: Porta TCP alvo.
        timeout: Tempo limite em segundos.

    Returns:
        True se a conexão TCP for bem-sucedida, False caso contrário.
    """
    if not host or port <= 0:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def parse_secrets_env_file(secrets_path: Path | None) -> dict[str, str]:
    """Extrai pares chave-valor de um arquivo `.env` com ou sem prefixo `export`.

    Args:
        secrets_path: Caminho para o arquivo de segredos configurado.

    Returns:
        Dicionário com as variáveis lidas do arquivo.
    """
    loaded: dict[str, str] = {}
    if secrets_path is None or not secrets_path.is_file():
        return loaded

    content = secrets_path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        clean_key = key.strip()
        clean_val = raw_val.strip().strip("\"'")
        if clean_key:
            loaded[clean_key] = clean_val
    return loaded


def validate_harness_config(config: HarnessLocalConfig) -> list[str]:
    """Valida se todos os itens mandatórios da configuração estão presentes.

    Args:
        config: Objeto populado de configuração do Harness.

    Returns:
        Lista com os nomes dos campos obrigatórios ausentes.
    """
    missing: list[str] = []
    has_redis_host = bool(config.redis.internal_host or config.redis.external_host)
    if not has_redis_host:
        missing.append("redis.internal_host / redis.external_host")

    has_redis_port = bool(
        config.redis.internal_port > 0 or config.redis.external_port > 0
    )
    if not has_redis_port:
        missing.append("redis.internal_port / redis.external_port")

    if not config.elasticsearch.index:
        missing.append("elasticsearch.index")

    has_es_url = bool(
        config.elasticsearch.internal_url or config.elasticsearch.external_url
    )
    if not has_es_url:
        missing.append("elasticsearch.internal_url / elasticsearch.external_url")

    has_llm_url = bool(config.llm.internal_base_url or config.llm.external_base_url)
    if not has_llm_url:
        missing.append("llm.internal_base_url / llm.external_base_url")

    has_llm_model = bool(config.llm.default_model or config.llm.judge_model)
    if not has_llm_model:
        missing.append("llm.default_model / llm.judge_model")

    if not config.spec_hub.github_org:
        missing.append("spec_hub.github_org")

    if not config.spec_hub.default_repo:
        missing.append("spec_hub.default_repo")

    if not config.spec_hub.flywheel_repo:
        missing.append("spec_hub.flywheel_repo")

    return missing


def first_env_value(*keys: str, default: str = "") -> str:
    """Retorna o primeiro valor não vazio entre as variáveis de ambiente listadas.

    Args:
        *keys: Nomes das variáveis de ambiente em ordem de prioridade.
        default: Valor padrão caso todas estejam vazias.

    Returns:
        String limpa correspondente à primeira variável encontrada ou `default`.
    """
    for key in keys:
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return default


def first_env_int(*keys: str, default: int = 0) -> int:
    """Retorna o primeiro valor inteiro não vazio entre as variáveis de ambiente.

    Args:
        *keys: Nomes das variáveis de ambiente em ordem de prioridade.
        default: Valor inteiro padrão caso todas estejam vazias.

    Returns:
        Valor inteiro convertido.
    """
    raw = first_env_value(*keys, default=str(default))
    return int(raw or default)


def set_env_if_missing(var_name: str, value: str) -> None:
    """Define uma variável em `os.environ` apenas se houver valor e ela estiver vazia.

    Args:
        var_name: Nome da variável de ambiente.
        value: Valor a ser atribuído caso `var_name` não esteja definido.
    """
    if value and not os.environ.get(var_name):
        os.environ[var_name] = value


def generate_config_from_env() -> HarnessLocalConfig:
    """Gera uma instância de HarnessLocalConfig a partir de variáveis de ambiente.

    Returns:
        HarnessLocalConfig populada com as variáveis definidas no ambiente.
    """
    redis_h = first_env_value("HARNESS_REDIS_HOST", "REDIS_HOST")
    redis_p = first_env_int("HARNESS_REDIS_PORT", "REDIS_PORT", default=0)
    redis_ext_h = first_env_value(
        "HARNESS_REDIS_EXTERNAL_HOST", "REDIS_EXTERNAL_HOST", default="127.0.0.1"
    )
    redis_ext_p = first_env_int(
        "HARNESS_REDIS_EXTERNAL_PORT",
        "REDIS_EXTERNAL_PORT",
        default=redis_p or 6379,
    )

    es_int = first_env_value("ES_INTERNAL_URL", "ES_URL", "ELASTICSEARCH_URL")
    es_ext = first_env_value("ES_EXTERNAL_URL", "ELASTICSEARCH_EXTERNAL_URL")
    es_idx = first_env_value("ES_INDEX", "ELASTICSEARCH_INDEX")

    llm_int = first_env_value(
        "LLM_INTERNAL_BASE_URL",
        "LLM_BASE_URL",
        "OLLAMA_BASE_URL",
        "OPENAI_BASE_URL",
    )
    llm_ext = first_env_value(
        "LLM_EXTERNAL_BASE_URL",
        "OPENAI_BASE_URL",
        "OLLAMA_EXTERNAL_BASE_URL",
    )
    llm_def_model = first_env_value("LLM_DEFAULT_MODEL", "LLM_MODEL")
    llm_jdg_model = first_env_value(
        "LLM_JUDGE_MODEL", "JUDGE_MODEL", "HARNESS_JUDGE_MODEL"
    )

    hub_org = first_env_value("SPEC_HUB_ORG", "GITHUB_ORG", "HARNESS_SPEC_HUB_ORG")
    hub_repo = first_env_value("SPEC_HUB_REPO", "HARNESS_SPEC_HUB_REPO")
    flywheel_repo = first_env_value("FLYWHEEL_REPO")
    secrets_file = first_env_value(
        "HARNESS_SECRETS_FILE", default="~/.harness-secrets.env"
    )

    ci_flag = first_env_value("CI", "GITHUB_ACTIONS").lower()
    is_ci = ci_flag in ("true", "1")

    ssh_host = first_env_value("SSH_TUNNEL_HOST", "SSH_HOST")
    ssh_user = first_env_value("SSH_TUNNEL_USER", "SSH_USER")
    ssh_port = first_env_int("SSH_TUNNEL_PORT", "SSH_PORT", default=22)
    tunnel_enabled = not is_ci and bool(ssh_host)

    ssh_cfg = SSHTunnelConfig(
        enabled=tunnel_enabled,
        auto_open_on_run=tunnel_enabled,
        host=ssh_host,
        user=ssh_user,
        port=ssh_port,
        local_bind_host=redis_ext_h,
        local_bind_port=redis_ext_p,
        remote_target_host=redis_h,
        remote_target_port=redis_p or 6379,
        connect_timeout_seconds=5,
    )

    lf_host = first_env_value(
        "LANGFUSE_HOST",
        "LANGFUSE_BASEURL",
        default="https://us.cloud.langfuse.com",
    )
    lf_public = first_env_value("LANGFUSE_PUBLIC_KEY")

    return HarnessLocalConfig(
        version="1.0",
        secrets=SecretsConfig(env_file=secrets_file),
        ssh_tunnel=ssh_cfg,
        redis=RedisEndpointsConfig(
            internal_host=redis_h,
            internal_port=redis_p,
            external_host=redis_ext_h,
            external_port=redis_ext_p,
            db=0,
        ),
        elasticsearch=ElasticsearchEndpointsConfig(
            internal_url=es_int,
            external_url=es_ext,
            index=es_idx,
        ),
        llm=LLMEndpointsConfig(
            internal_base_url=llm_int,
            external_base_url=llm_ext,
            default_model=llm_def_model,
            judge_model=llm_jdg_model,
        ),
        spec_hub=SpecHubConfig(
            github_org=hub_org,
            default_repo=hub_repo,
            flywheel_repo=flywheel_repo,
            local_relative_path="../paralax-spec-hub",
        ),
        langfuse=LangfuseConfig(
            host=lf_host,
            public_key=lf_public,
        ),
    )


def save_harness_config_file(config: HarnessLocalConfig, target_path: Path) -> Path:
    """Grava as configurações em arquivo YAML no destino especificado.

    Args:
        config: Objeto de configuração populado.
        target_path: Caminho do arquivo a ser gravado.

    Returns:
        Path do arquivo gravado.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump()
    yaml_text = yaml.safe_dump(payload, sort_keys=False)
    target_path.write_text(yaml_text, encoding="utf-8")
    return target_path


def resolve_config_path(
    project_root: Path | None = None,
    explicit_path: Path | None = None,
) -> Path | None:
    """Resolve qual arquivo `config.yaml` existente deve ser lido pelo pipeline.

    Ordem de precedência:
    1. `explicit_path` passado por parâmetro.
    2. Variável de ambiente `HARNESS_CONFIG_FILE`.
    3. `<project_root>/.harness/config.yaml` (override local do módulo).
    4. `~/.config/harness/config.yaml` (configuração global do usuário).

    Args:
        project_root: Raiz opcional do módulo local.
        explicit_path: Caminho explícito opcional.

    Returns:
        Path resolvido se o arquivo existir, ou None caso não exista arquivo.

    Raises:
        ConfigurationError: Se um caminho explícito fornecido não existir.
    """
    if explicit_path is not None:
        resolved = explicit_path.expanduser().resolve()
        if resolved.is_file():
            return resolved
        return None

    if project_root is not None:
        project_cfg = project_root.resolve() / ".harness" / "config.yaml"
        if project_cfg.is_file():
            return project_cfg

    env_cfg = os.environ.get("HARNESS_CONFIG_FILE", "").strip()
    if env_cfg:
        resolved = Path(env_cfg).expanduser().resolve()
        if not resolved.is_file():
            raise ConfigurationError(
                "Arquivo de configuração em HARNESS_CONFIG_FILE não encontrado: "
                f"{env_cfg}"
            )
        return resolved

    user_cfg = get_default_user_config_path()
    if user_cfg.is_file():
        return user_cfg

    return None


def load_harness_config(
    project_root: Path | None = None,
    explicit_path: Path | None = None,
    ensure_exists: bool = True,
) -> tuple[HarnessLocalConfig, Path]:
    """Carrega e valida o arquivo de configuração local do Harness.

    Se o arquivo não existir e `ensure_exists` for True, gera o arquivo a partir
    das variáveis de ambiente. Se a configuração não existir ou faltar algum item
    obrigatório, dispara ConfigurationError.

    Args:
        project_root: Raiz opcional do pacote local.
        explicit_path: Caminho opcional explícito para o `config.yaml`.
        ensure_exists: Se True, gera e persiste o arquivo a partir do ambiente
            se ausente.

    Returns:
        Tupla `(HarnessLocalConfig, Path_do_arquivo)`.

    Raises:
        ConfigurationError: Se a configuração não existir ou estiver incompleta.
    """
    cfg_path = resolve_config_path(
        project_root=project_root,
        explicit_path=explicit_path,
    )
    if cfg_path is not None:
        raw_text = cfg_path.read_text(encoding="utf-8")
        try:
            parsed = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise ConfigurationError(
                f"Falha ao interpretar arquivo YAML '{cfg_path}': {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ConfigurationError(
                f"Arquivo de configuração '{cfg_path}' não contém um mapa YAML válido."
            )

        config = HarnessLocalConfig.model_validate(parsed)
        missing = validate_harness_config(config)
        if missing:
            raise ConfigurationError(
                f"Arquivo de configuração '{cfg_path}' possui itens obrigatórios "
                f"ausentes: {', '.join(missing)}"
            )
        return config, cfg_path

    if not ensure_exists:
        if explicit_path is not None:
            raise ConfigurationError(
                f"Arquivo de configuração explícito não encontrado: {explicit_path}"
            )
        raise ConfigurationError(
            "Nenhum arquivo de configuração encontrado e ensure_exists está desativado."
        )

    env_config = generate_config_from_env()
    missing = validate_harness_config(env_config)
    if missing:
        raise ConfigurationError(
            "Nenhum arquivo de configuração encontrado e variáveis de ambiente "
            f"obrigatórias estão ausentes para gerá-lo: {', '.join(missing)}"
        )

    if explicit_path is not None:
        target_path = explicit_path.expanduser().resolve()
        save_harness_config_file(env_config, target_path)
        return env_config, target_path

    target_path = get_default_user_config_path()
    save_harness_config_file(env_config, target_path)
    return env_config, target_path


def get_active_config(project_root: Path | None = None) -> HarnessLocalConfig:
    """Retorna a configuração ativa combinando `config.yaml` e variáveis de ambiente.

    Tenta carregar o arquivo existente. Se nenhum arquivo de configuração válido
    existir no módulo ou ambiente, retorna os valores instanciados das variáveis.

    Args:
        project_root: Raiz opcional do módulo local.

    Returns:
        Instância de `HarnessLocalConfig` populada.
    """
    cfg_path = resolve_config_path(project_root=project_root)
    if cfg_path is not None and cfg_path.is_file():
        try:
            config, _ = load_harness_config(
                project_root=project_root,
                ensure_exists=False,
            )
            return config
        except ConfigurationError:
            pass
    return generate_config_from_env()


def apply_redis_and_es_env(
    config: HarnessLocalConfig,
    internal_reachable: bool,
    applied: dict[str, str],
) -> None:
    """Injeta variáveis de ambiente de Redis e Elasticsearch em `os.environ`.

    Args:
        config: Instância carregada de `HarnessLocalConfig`.
        internal_reachable: Se True, prioriza endereços internos.
        applied: Dicionário mutável de variáveis aplicadas.
    """
    redis_host = (
        config.redis.internal_host if internal_reachable else config.redis.external_host
    )
    redis_port = (
        config.redis.internal_port if internal_reachable else config.redis.external_port
    )
    redis_url = config.build_redis_url(use_internal=internal_reachable)

    set_env_if_missing("HARNESS_REDIS_URL", redis_url)
    set_env_if_missing("HARNESS_REDIS_HOST", redis_host)
    set_env_if_missing("HARNESS_REDIS_PORT", str(redis_port) if redis_port else "")

    applied["HARNESS_REDIS_URL"] = os.environ.get("HARNESS_REDIS_URL", "")
    applied["HARNESS_REDIS_HOST"] = os.environ.get("HARNESS_REDIS_HOST", "")
    applied["HARNESS_REDIS_PORT"] = os.environ.get("HARNESS_REDIS_PORT", "")

    es_internal = config.elasticsearch.internal_url.rstrip("/")
    es_external = config.elasticsearch.external_url.rstrip("/")
    if es_internal:
        os.environ["ES_INTERNAL_URL"] = es_internal
    if es_external:
        os.environ["ES_EXTERNAL_URL"] = es_external
    set_env_if_missing("ES_INDEX", config.elasticsearch.index)

    es_url = config.resolve_elasticsearch_url(use_internal=internal_reachable)
    set_env_if_missing("ES_URL", es_url)

    applied["ES_INTERNAL_URL"] = os.environ.get("ES_INTERNAL_URL", "")
    applied["ES_EXTERNAL_URL"] = os.environ.get("ES_EXTERNAL_URL", "")
    applied["ES_URL"] = os.environ.get("ES_URL", "")
    applied["ES_INDEX"] = os.environ.get("ES_INDEX", "")


def apply_llm_and_hub_env(
    config: HarnessLocalConfig,
    internal_reachable: bool,
    secrets_map: dict[str, str],
    applied: dict[str, str],
) -> None:
    """Injeta variáveis de LLM, Spec-Hub e Langfuse em `os.environ`.

    Args:
        config: Instância carregada de `HarnessLocalConfig`.
        internal_reachable: Se True, usa base URL interna da LLM.
        secrets_map: Mapa de chaves lidas do arquivo de segredos.
        applied: Dicionário mutável de variáveis aplicadas.
    """
    llm_url = (
        config.llm.internal_base_url
        if internal_reachable
        else config.llm.external_base_url
    )
    set_env_if_missing("OPENAI_BASE_URL", llm_url)
    set_env_if_missing("HARNESS_JUDGE_MODEL", config.llm.judge_model)
    set_env_if_missing("LLM_JUDGE_MODEL", config.llm.judge_model)
    set_env_if_missing("JUDGE_MODEL", config.llm.judge_model)
    set_env_if_missing("HARNESS_GITHUB_ORG", config.spec_hub.github_org)
    set_env_if_missing("HARNESS_SPEC_HUB_REPO", config.spec_hub.default_repo)
    set_env_if_missing("HARNESS_FLYWHEEL_REPO", config.spec_hub.flywheel_repo)

    llm_api_key = (
        first_env_value("OLLAMA_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
        or secrets_map.get("OLLAMA_API_KEY")
        or secrets_map.get("LLM_API_KEY")
        or secrets_map.get("OPENAI_API_KEY")
        or ""
    )
    if llm_api_key:
        set_env_if_missing("OPENAI_API_KEY", llm_api_key)
        set_env_if_missing("LLM_API_KEY", llm_api_key)
        applied["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
        applied["LLM_API_KEY"] = os.environ["LLM_API_KEY"]

    applied["OPENAI_BASE_URL"] = os.environ.get("OPENAI_BASE_URL", "")
    lf_host = (
        config.langfuse.host
        or os.environ.get("LANGFUSE_HOST")
        or "https://us.cloud.langfuse.com"
    )
    set_env_if_missing("LANGFUSE_HOST", lf_host)
    set_env_if_missing("LANGFUSE_PUBLIC_KEY", config.langfuse.public_key)

    applied["LANGFUSE_HOST"] = os.environ.get("LANGFUSE_HOST", "")
    applied["LANGFUSE_PUBLIC_KEY"] = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    applied["LANGFUSE_SECRET_KEY"] = (
        "configurada" if os.environ.get("LANGFUSE_SECRET_KEY") else "ausente"
    )


def apply_config_to_environment(
    config: HarnessLocalConfig,
    config_path: Path | None = None,
    ci_mode: bool = False,
    port_checker: Callable[[str, int, float], bool] = is_tcp_port_open,
) -> dict[str, str]:
    """Injeta todas as configurações e segredos no `os.environ` para o pipeline.

    Args:
        config: Instância carregada de `HarnessLocalConfig`.
        config_path: Caminho do arquivo `config.yaml` utilizado.
        ci_mode: Se True, prioriza os endereços internos da Cloud.
        port_checker: Função injetável para checagem de conectividade TCP.

    Returns:
        Dicionário com as variáveis de ambiente aplicadas.
    """
    applied: dict[str, str] = {}

    if config_path is not None:
        os.environ["HARNESS_CONFIG_FILE"] = str(config_path)
        applied["HARNESS_CONFIG_FILE"] = str(config_path)

    secrets_path = config.resolve_secrets_path()
    if secrets_path is not None:
        os.environ["HARNESS_SECRETS_FILE"] = str(secrets_path)
        applied["HARNESS_SECRETS_FILE"] = str(secrets_path)

    secrets_map = parse_secrets_env_file(secrets_path)
    for key, value in secrets_map.items():
        set_env_if_missing(key, value)
        applied[key] = os.environ[key]

    internal_redis_reachable = ci_mode or port_checker(
        config.redis.internal_host, config.redis.internal_port, 0.2
    )
    apply_redis_and_es_env(config, internal_redis_reachable, applied)
    apply_llm_and_hub_env(config, internal_redis_reachable, secrets_map, applied)
    return applied


class SSHTunnelManager:
    """Gerenciador de ciclo de vida do túnel SSH para o Redis."""

    def __init__(
        self,
        port_checker: Callable[[str, int, float], bool] = is_tcp_port_open,
        command_runner: Callable[[list[str]], subprocess.CompletedProcess]
        | None = None,
    ) -> None:
        """Inicializa o gerenciador com verificador de porta e executor SSH.

        Args:
            port_checker: Callback para testar se uma porta TCP está aberta.
            command_runner: Callback opcional para executar o comando `ssh`.
        """
        self.port_checker = port_checker
        self.command_runner = command_runner or self._default_command_runner

    def _default_command_runner(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """Executa o binário `ssh` em subprocesso.

        Args:
            cmd: Lista de argumentos do comando SSH.

        Returns:
            Instância de `CompletedProcess`.
        """
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

    def build_ssh_command(self, tunnel_cfg: SSHTunnelConfig) -> list[str]:
        """Monta o comando `ssh -f -N -L ...` a partir da configuração.

        Args:
            tunnel_cfg: Configuração do túnel SSH.

        Returns:
            Lista de argumentos prontos para execução.
        """
        forward_spec = (
            f"{tunnel_cfg.local_bind_host}:{tunnel_cfg.local_bind_port}:"
            f"{tunnel_cfg.remote_target_host}:{tunnel_cfg.remote_target_port}"
        )
        return [
            "ssh",
            "-f",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            f"ConnectTimeout={tunnel_cfg.connect_timeout_seconds}",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "TCPKeepAlive=yes",
            "-p",
            str(tunnel_cfg.port),
            "-L",
            forward_spec,
            f"{tunnel_cfg.user}@{tunnel_cfg.host}",
        ]

    def terminate_existing_tunnel(self, tunnel_cfg: SSHTunnelConfig) -> None:
        """Encerra processos locais de SSH associados ao bind da porta do túnel.

        Args:
            tunnel_cfg: Configuração do túnel SSH contendo porta e host local.
        """
        pattern = (
            f"{tunnel_cfg.local_bind_port}:"
            f"{tunnel_cfg.remote_target_host}:{tunnel_cfg.remote_target_port}"
        )
        try:
            subprocess.run(
                ["pkill", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            pass

    def ensure_tunnel(
        self,
        config: HarnessLocalConfig,
        ci_mode: bool = False,
        force_reconnect: bool = False,
    ) -> TunnelStatus:
        """Garante que o túnel SSH para o Redis esteja aberto quando em modo local.

        Args:
            config: Configuração local do Harness.
            ci_mode: Se True, não abre túnel SSH pois roda na rede da Cloud.
            force_reconnect: Se True, fecha processos residuais e reabre o túnel.

        Returns:
            `TunnelStatus` descrevendo se o túnel já estava ativo ou foi aberto agora.
        """
        tunnel_cfg = config.ssh_tunnel
        if (
            ci_mode
            or not tunnel_cfg.enabled
            or not tunnel_cfg.auto_open_on_run
            or not tunnel_cfg.host
        ):
            return TunnelStatus(
                active=False,
                opened_now=False,
                reason="disabled_or_ci",
            )

        if not force_reconnect and self.port_checker(
            config.redis.internal_host, config.redis.internal_port, 0.2
        ):
            return TunnelStatus(
                active=True,
                opened_now=False,
                reason="internal_network_direct",
            )

        if not force_reconnect and self.port_checker(
            tunnel_cfg.local_bind_host, tunnel_cfg.local_bind_port, 0.2
        ):
            return TunnelStatus(
                active=True,
                opened_now=False,
                reason="already_listening",
            )

        if force_reconnect:
            self.terminate_existing_tunnel(tunnel_cfg)

        ssh_cmd = self.build_ssh_command(tunnel_cfg)
        cmd_str = " ".join(ssh_cmd)
        proc = self.command_runner(ssh_cmd)
        if proc.returncode != 0:
            err_detail = (proc.stderr or proc.stdout or "ssh_failed").strip()
            return TunnelStatus(
                active=False,
                opened_now=False,
                reason=f"ssh_error: {err_detail}",
                command=cmd_str,
            )

        return TunnelStatus(
            active=True,
            opened_now=True,
            reason="opened_ssh_tunnel",
            command=cmd_str,
        )

    def reconnect_tunnel(
        self,
        config: HarnessLocalConfig,
        ci_mode: bool = False,
    ) -> TunnelStatus:
        """Força a reabertura do túnel SSH para o Redis fechando conexões residuais.

        Args:
            config: Configuração local do Harness.
            ci_mode: Se True, não realiza nenhuma ação (modo Cloud).

        Returns:
            Instância de `TunnelStatus` indicando o resultado da reconexão.
        """
        return self.ensure_tunnel(
            config=config,
            ci_mode=ci_mode,
            force_reconnect=True,
        )


def main() -> None:
    """Ponto de entrada para `python -m harness_state.config`."""
    import sys

    try:
        cfg, path = load_harness_config(ensure_exists=True)
        print(
            f"[Harness Config] ✓ Configuração v{cfg.version} validada com sucesso em: {path}"
        )
    except ConfigurationError as exc:
        print(f"[Harness Config] ❌ Erro de configuração: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

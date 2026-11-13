"""Ciclo de vida de prompts com Langfuse como fonte da verdade (SPEC-PROMPT-01).

Princípios fundamentais:
1. O Langfuse é a fonte da verdade para todos os prompts produtivos.
2. Antes de alterar um prompt localmente, baixa-se a versão mais recente do Langfuse.
3. A nova versão do prompt é criada no Langfuse em modo rascunho/draft (nunca
   'production' diretamente).
4. O arquivo de código local (ex: prompts.py) é atualizado com o fallback da
   nova versão.
5. A marcação do prompt como 'production' no Langfuse ocorre exclusivamente
   após a aprovação do PR.
"""

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class PromptManagementError(Exception):
    """Exceção levantada em falhas operacionais do gerenciador de prompts."""


class LangfusePromptManager:
    """Cliente e gerenciador do ciclo de vida de prompts no Langfuse."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
    ) -> None:
        """Inicializa o gerenciador com credenciais lidas do ambiente.

        Args:
            public_key: Chave pública da API do Langfuse.
            secret_key: Chave secreta da API do Langfuse.
            host: URL base do servidor Langfuse.
        """
        if public_key is not None:
            self.public_key = public_key
        else:
            self.public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")

        if secret_key is not None:
            self.secret_key = secret_key
        else:
            self.secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

        env_host = (
            os.environ.get("LANGFUSE_HOST")
            or os.environ.get("LANGFUSE_BASEURL")
            or "https://cloud.langfuse.com"
        )
        raw_host = host if host is not None else env_host
        self.host = raw_host.rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Indica se as credenciais necessárias do Langfuse estão configuradas.

        Returns:
            True se public_key e secret_key estiverem presentes.
        """
        return bool(self.public_key and self.secret_key)

    def _build_auth_header(self) -> str:
        """Gera o cabeçalho HTTP Basic Auth para a API do Langfuse.

        Returns:
            String no formato 'Basic <base64>'.
        """
        credentials = f"{self.public_key}:{self.secret_key}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def fetch_prompt(
        self,
        prompt_name: str,
        version: int | None = None,
        label: str | None = None,
    ) -> tuple[str, int]:
        """Baixa a especificação e conteúdo do prompt no Langfuse.

        Args:
            prompt_name: Nome do prompt registrado no Langfuse.
            version: Versão numérica opcional.
            label: Label opcional (ex: production, draft).

        Returns:
            Tupla contendo `(prompt_text, version_number)`.

        Raises:
            PromptManagementError: Em caso de falha de comunicação ou erro de API.
        """
        if not self.is_configured:
            raise PromptManagementError(
                "Langfuse não configurado. Defina LANGFUSE_PUBLIC_KEY e "
                "LANGFUSE_SECRET_KEY no ambiente."
            )

        encoded_name = urllib.parse.quote(prompt_name, safe="")
        query_params: dict[str, str] = {}
        if version is not None:
            query_params["version"] = str(version)
        elif label:
            query_params["label"] = label

        url = f"{self.host}/api/public/v2/prompts/{encoded_name}"
        if query_params:
            url += f"?{urllib.parse.urlencode(query_params)}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self._build_auth_header(),
                "Content-Type": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prompt_text = data.get("prompt", "")
                if isinstance(prompt_text, list):
                    prompt_text = json.dumps(prompt_text, indent=2, ensure_ascii=False)
                prompt_version = int(data.get("version", 1))
                return str(prompt_text), prompt_version
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PromptManagementError(
                f"Falha ao buscar prompt '{prompt_name}' no Langfuse: {exc}"
            ) from exc

    def push_draft(
        self,
        prompt_name: str,
        prompt_text: str,
        label: str = "draft",
        prompt_type: str = "text",
    ) -> int:
        """Cria uma nova versão do prompt no Langfuse com a label especificada.

        NUNCA publica com a label 'production' diretamente neste método.

        Args:
            prompt_name: Nome do prompt (ex: paralax/support).
            prompt_text: Conteúdo textual do novo prompt.
            label: Label de estágio (draft, staging, etc.).
            prompt_type: Tipo do prompt ('text' ou 'chat').

        Returns:
            Número da versão criada no Langfuse.

        Raises:
            PromptManagementError: Em falhas de requisição ou rejeição pela API.
        """
        if not self.is_configured:
            raise PromptManagementError(
                "Langfuse não configurado. Defina LANGFUSE_PUBLIC_KEY e "
                "LANGFUSE_SECRET_KEY."
            )

        # Garante que rascunhos nunca usem a tag production diretamente
        applied_labels = ["draft"] if label == "production" else [label]

        payload = {
            "name": prompt_name,
            "prompt": prompt_text,
            "type": prompt_type,
            "labels": applied_labels,
        }

        url = f"{self.host}/api/public/v2/prompts"
        data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Authorization": self._build_auth_header(),
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                version = int(data.get("version", 1))
                return version
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PromptManagementError(
                f"Falha ao registrar versão draft do prompt '{prompt_name}': {exc}"
            ) from exc

    def promote_to_production(
        self,
        prompt_name: str,
        version: int | None = None,
    ) -> bool:
        """Promove uma versão do prompt para a label 'production' no Langfuse.

        Deve ser executado exclusivamente após a aprovação formal do Pull Request.

        Args:
            prompt_name: Nome do prompt.
            version: Número opcional da versão. Se omitido, promove a mais recente.

        Returns:
            True se a promoção foi concluída com sucesso.

        Raises:
            PromptManagementError: Em caso de falha de promoção.
        """
        if not self.is_configured:
            raise PromptManagementError("Langfuse não configurado.")

        target_version = version
        prompt_content = ""
        if target_version is None:
            try:
                prompt_content, target_version = self.fetch_prompt(
                    prompt_name, label="latest"
                )
            except PromptManagementError:
                prompt_content, target_version = self.fetch_prompt(prompt_name)
        else:
            prompt_content, _ = self.fetch_prompt(prompt_name, version=target_version)

        url = f"{self.host}/api/public/v2/prompts"
        payload = {
            "name": prompt_name,
            "prompt": prompt_content,
            "labels": ["production"],
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Authorization": self._build_auth_header(),
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except urllib.error.URLError as exc:
            raise PromptManagementError(
                f"Falha ao promover prompt '{prompt_name}' para produção: {exc}"
            ) from exc

    def update_local_fallback(
        self,
        file_path: Path,
        prompt_text: str,
        variable_name: str = "INSTRUCTION",
    ) -> bool:
        """Atualiza a variável de fallback no código Python local preservando o módulo.

        Args:
            file_path: Caminho do arquivo Python de prompts (ex: support/prompts.py).
            prompt_text: Novo conteúdo do prompt a ser atribuído à variável.
            variable_name: Nome da constante no arquivo (padrão: INSTRUCTION).

        Returns:
            True se o arquivo foi atualizado com sucesso.

        Raises:
            PromptManagementError: Se o arquivo ou a variável não for localizada.
        """
        if not file_path.is_file():
            raise PromptManagementError(f"Arquivo local {file_path} não encontrado.")

        content = file_path.read_text(encoding="utf-8")

        # Padrão para capturar VARIABLE = \"\"\"...\"\"\" ou VARIABLE = '''...'''
        pattern = re.compile(
            rf'(^{variable_name}\s*=\s*)(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
            re.MULTILINE,
        )

        escaped_prompt = prompt_text.replace('"""', r"\"\"\"")
        replacement = f'{variable_name} = """{escaped_prompt}"""'

        if pattern.search(content):
            new_content = pattern.sub(replacement, content)
            file_path.write_text(new_content, encoding="utf-8")
            return True

        # Fallback se a variável for declarada em linha única
        single_pattern = re.compile(
            rf'(^{variable_name}\s*=\s*)(["\'].*?["\'])', re.MULTILINE
        )
        if single_pattern.search(content):
            new_content = single_pattern.sub(replacement, content)
            file_path.write_text(new_content, encoding="utf-8")
            return True

        raise PromptManagementError(
            f"Variável '{variable_name}' não encontrada no arquivo {file_path}."
        )

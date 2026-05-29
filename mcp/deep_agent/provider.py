"""Provider adapter path for the Deep Agent platform (S21.bedrock.1).

The platform's default model seam is ``llm.chat_model(role=...)``, which builds
a ``ChatOpenAI`` pointed at an OpenAI-compatible endpoint (SGLang/vLLM, or any
gateway that speaks the protocol). This module adds a thin **provider switch**
so a role (and therefore an agent profile) can be pointed at **Amazon Bedrock**
instead, without changing any of the OpenAI-compatible call sites.

Design
------
* Provider is resolved per role from ``<PREFIX>_PROVIDER`` (the same env the
  Stage-26 ``role_runtime`` visibility surface already reads via
  ``llm._provider_for``). ``bedrock`` selects this adapter; everything else
  falls through to the unchanged ``ChatOpenAI`` path.
* For ``bedrock`` we build a ``langchain_aws.ChatBedrockConverse`` model. That
  package is an **optional** dependency: the OpenAI-compatible deployment does
  not install it, so importing it is deferred to call time and a missing import
  raises a clear, actionable error (rather than breaking module load for every
  deployment). This is the "explicitly stubbed with interface + envs + IAM
  requirements" path the task allows — wiring + interface are complete; enabling
  it is `pip install langchain-aws boto3` + the IAM/region envs below.

Model ID mapping
----------------
A profile's ``model`` is an OpenAI-style id (e.g. ``qwen3.6-27b``). Bedrock
needs a Bedrock model id (e.g. ``anthropic.claude-3-5-sonnet-20241022-v2:0``).
The mapping is, in order:
  1. an explicit ``<PREFIX>_BEDROCK_MODEL`` env (wins),
  2. the role/profile ``model`` if it already looks like a Bedrock id
     (contains a ``.`` provider prefix and no whitespace),
  3. otherwise an error telling the operator to set the env — we never guess a
     billed model id.

IAM / region
------------
Bedrock auth is **not** an API key. It uses the standard AWS credential chain
(IAM role on ECS/EKS task, instance profile, or ``AWS_*`` env). Region comes
from ``<PREFIX>_BEDROCK_REGION`` (falling back to ``AWS_REGION`` /
``AWS_DEFAULT_REGION``). The task/pod role needs ``bedrock:InvokeModel`` and
``bedrock:InvokeModelWithResponseStream`` on the target model ARNs.
"""

from __future__ import annotations

import os
from typing import Any

from llm import _ROLE_PREFIX, _role_env, chat_model  # reuse the role registry


class ProviderConfigError(RuntimeError):
    """Misconfigured provider adapter (missing model id, region, or package)."""


def provider_for_role(role: str = "default") -> str:
    """The configured provider for a role: explicit ``<PREFIX>_PROVIDER`` or
    ``openai-compatible``. Mirrors ``llm._provider_for`` but without needing the
    base_url (the env is authoritative when set)."""
    prefix = _ROLE_PREFIX.get(role, "UPSTREAM")
    explicit = os.environ.get(f"{prefix}_PROVIDER")
    if explicit:
        return explicit.lower()
    # Fall back to host inference for back-compat with role_runtime.
    base, _model, _key = _role_env(prefix)
    from llm import _provider_for

    return _provider_for(prefix, base)


def _bedrock_model_id(prefix: str, role_model: str) -> str:
    explicit = os.environ.get(f"{prefix}_BEDROCK_MODEL")
    if explicit:
        return explicit
    # A Bedrock id looks like "anthropic.claude-3-5-sonnet-20241022-v2:0" — the
    # segment before the first dot is a *provider word* (alphabetic), not a
    # version number. Accept the profile model as-is only if it matches that
    # shape; a version-dotted OpenAI-style name like "Qwen3.6-27b" must NOT be
    # mistaken for a billed Bedrock id, so we refuse and ask for the env.
    head = role_model.split("/")[-1].split(".")[0] if role_model else ""
    looks_bedrock = bool(head) and head.isalpha() and "." in role_model and " " not in role_model
    if looks_bedrock:
        return role_model
    raise ProviderConfigError(
        f"provider=bedrock for prefix {prefix} but no Bedrock model id: set "
        f"{prefix}_BEDROCK_MODEL (e.g. anthropic.claude-3-5-sonnet-20241022-v2:0)."
    )


def _bedrock_region(prefix: str) -> str:
    region = (
        os.environ.get(f"{prefix}_BEDROCK_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    if not region:
        raise ProviderConfigError(
            f"provider=bedrock for prefix {prefix} but no region: set "
            f"{prefix}_BEDROCK_REGION or AWS_REGION."
        )
    return region


def chat_model_for_role(temperature: float = 0.2, role: str = "default") -> Any:
    """Return a LangChain chat model for a role, honoring the provider switch.

    Drop-in for ``llm.chat_model`` at the deep-agent call sites: returns a
    ``ChatBedrockConverse`` when the role's provider is ``bedrock``, otherwise
    the unchanged ``ChatOpenAI``. Keeping a single entry point means a profile
    flips providers by env alone — no code path in ``runtime.py`` changes.
    """
    provider = provider_for_role(role)
    if provider != "bedrock":
        return chat_model(temperature=temperature, role=role)

    prefix = _ROLE_PREFIX.get(role, "UPSTREAM")
    _base, role_model, _key = _role_env(prefix)
    model_id = _bedrock_model_id(prefix, role_model)
    region = _bedrock_region(prefix)
    try:
        from langchain_aws import ChatBedrockConverse  # type: ignore
    except ImportError as e:  # optional dependency — clear remediation
        raise ProviderConfigError(
            "provider=bedrock requires the optional dependencies: "
            "`pip install langchain-aws boto3`. The OpenAI-compatible path needs "
            "neither and is unaffected."
        ) from e
    # Credentials come from the standard AWS chain (IAM task/instance role or
    # AWS_* env) — never an API key. boto3 resolves them automatically.
    return ChatBedrockConverse(model=model_id, region_name=region, temperature=temperature)


def provider_summary() -> dict[str, Any]:
    """Redacted per-role provider mapping for runtime visibility / docs.

    Never includes credentials. For bedrock roles, reports the resolved model
    id + region when configured, or the config gap if not (so an operator sees
    exactly what's missing). Safe to call without ``langchain-aws`` installed."""
    out: dict[str, Any] = {}
    for role, prefix in _ROLE_PREFIX.items():
        provider = provider_for_role(role)
        entry: dict[str, Any] = {"provider": provider}
        if provider == "bedrock":
            try:
                _base, role_model, _key = _role_env(prefix)
                entry["model_id"] = _bedrock_model_id(prefix, role_model)
                entry["region"] = _bedrock_region(prefix)
                entry["credentials"] = "AWS credential chain (IAM role / AWS_* env)"
            except ProviderConfigError as e:
                entry["config_error"] = str(e)
        out[role] = entry
    return out

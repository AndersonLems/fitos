"""Adaptador GroqCloud Chat Completions para a interface de geração usada pelo FitOS."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from google.genai import types

from config.settings import GROQ_MODEL_DEFAULT, groq_api_key


def generate_content(*, contents, config):
    key = groq_api_key()
    if not key:
        raise ValueError("Chave GroqCloud ausente")
    inputs = []
    if isinstance(contents, str):
        inputs.append({"role": "user", "content": contents})
    else:
        # Histórico de ferramentas vira contexto textual: ações continuam sendo
        # validadas e confirmadas pelo chat_service, nunca executadas pelo provedor.
        for content in contents:
            parts = []
            for part in content.parts or []:
                if part.text:
                    parts.append(part.text)
                if part.function_call:
                    call = part.function_call
                    parts.append(f"Ação proposta: {call.name} {json.dumps(call.args, ensure_ascii=False)}")
                if part.function_response:
                    result = part.function_response
                    parts.append(f"Resultado de {result.name}: {json.dumps(result.response, ensure_ascii=False)}")
            if parts:
                inputs.append({"role": "assistant" if content.role == "model" else "user",
                               "content": "\n".join(parts)})
    system = getattr(config, "system_instruction", None) or "Responda em português."
    schema = getattr(config, "response_schema", None)
    if schema:
        system += "\nResponda somente com JSON conforme este esquema:\n" + json.dumps(schema.model_json_schema())
    payload = {"model": GROQ_MODEL_DEFAULT, "messages": [{"role": "system", "content": system}, *inputs]}
    if schema:
        payload["response_format"] = {"type": "json_object"}
    limit = getattr(config, "max_output_tokens", None)
    if limit:
        payload["max_completion_tokens"] = limit
    temperature = getattr(config, "temperature", None)
    if temperature is not None:
        payload["temperature"] = temperature
    declarations = [decl for tool in (getattr(config, "tools", None) or [])
                    for decl in (tool.function_declarations or [])]
    if declarations:
        payload["tools"] = [{"type": "function", "function": {
            "name": d.name, "description": d.description or "",
            "parameters": d.parameters_json_schema or {"type": "object", "properties": {}}
        }} for d in declarations]
    with httpx.Client(timeout=60) as client:
        response = client.post("https://api.groq.com/openai/v1/chat/completions", json=payload,
                               headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        data = response.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") not in ("stop", "tool_calls"):
        raise ValueError("Resposta GroqCloud incompleta")
    message = choice["message"]
    parts, calls, texts = [], [], []
    if message.get("content"):
        texts.append(message["content"])
        parts.append(types.Part(text=message["content"]))
    for item in message.get("tool_calls") or []:
        function = item["function"]
        call = types.FunctionCall(name=function["name"], args=json.loads(function["arguments"]))
        calls.append(call)
        parts.append(types.Part(function_call=call))
    if not texts and not calls:
        raise ValueError("Resposta GroqCloud vazia")
    usage = data.get("usage") or {}
    return SimpleNamespace(text="\n".join(texts), parsed=None, function_calls=calls,
                           candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
                           usage_metadata=SimpleNamespace(prompt_token_count=usage.get("prompt_tokens"),
                                                          candidates_token_count=usage.get("completion_tokens")))

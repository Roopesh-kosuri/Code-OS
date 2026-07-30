from pydantic import BaseModel


class ModelMetadata(BaseModel):
    id: str
    name: str
    provider: str
    context_window: int
    input_cost_per_m: float
    output_cost_per_m: float
    supports_streaming: bool = True
    supports_tools: bool = True


PROVIDER_CATALOG: dict[str, list[ModelMetadata]] = {
    "ollama": [
        ModelMetadata(id="llama3", name="Llama 3 8B", provider="ollama", context_window=8192, input_cost_per_m=0.0, output_cost_per_m=0.0),
        ModelMetadata(id="qwen2.5-coder", name="Qwen 2.5 Coder 7B", provider="ollama", context_window=32768, input_cost_per_m=0.0, output_cost_per_m=0.0),
        ModelMetadata(id="mistral", name="Mistral 7B", provider="ollama", context_window=8192, input_cost_per_m=0.0, output_cost_per_m=0.0),
    ],
    "openai": [
        ModelMetadata(id="gpt-4o", name="GPT-4o", provider="openai", context_window=128000, input_cost_per_m=2.50, output_cost_per_m=10.00),
        ModelMetadata(id="gpt-4o-mini", name="GPT-4o Mini", provider="openai", context_window=128000, input_cost_per_m=0.15, output_cost_per_m=0.60),
        ModelMetadata(id="o3-mini", name="o3-mini", provider="openai", context_window=200000, input_cost_per_m=1.10, output_cost_per_m=4.40),
    ],
    "anthropic": [
        ModelMetadata(id="claude-3-5-sonnet-latest", name="Claude 3.5 Sonnet", provider="anthropic", context_window=200000, input_cost_per_m=3.00, output_cost_per_m=15.00),
        ModelMetadata(id="claude-3-5-haiku-latest", name="Claude 3.5 Haiku", provider="anthropic", context_window=200000, input_cost_per_m=0.80, output_cost_per_m=4.00),
        ModelMetadata(id="claude-3-opus-latest", name="Claude 3 Opus", provider="anthropic", context_window=200000, input_cost_per_m=15.00, output_cost_per_m=75.00),
    ],
    "groq": [
        ModelMetadata(id="llama-3.3-70b-versatile", name="Llama 3.3 70B", provider="groq", context_window=128000, input_cost_per_m=0.59, output_cost_per_m=0.79),
        ModelMetadata(id="mixtral-8x7b-32768", name="Mixtral 8x7B", provider="groq", context_window=32768, input_cost_per_m=0.24, output_cost_per_m=0.24),
    ],
    "deepseek": [
        ModelMetadata(id="deepseek-chat", name="DeepSeek V3", provider="deepseek", context_window=64000, input_cost_per_m=0.14, output_cost_per_m=0.28),
        ModelMetadata(id="deepseek-reasoner", name="DeepSeek R1", provider="deepseek", context_window=64000, input_cost_per_m=0.55, output_cost_per_m=2.19),
    ],
    "gemini": [
        ModelMetadata(id="gemini-2.5-flash", name="Gemini 2.5 Flash", provider="gemini", context_window=1000000, input_cost_per_m=0.075, output_cost_per_m=0.30),
        ModelMetadata(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="gemini", context_window=2000000, input_cost_per_m=1.25, output_cost_per_m=5.00),
    ],
    "mistral": [
        ModelMetadata(id="mistral-large-latest", name="Mistral Large", provider="mistral", context_window=128000, input_cost_per_m=2.00, output_cost_per_m=6.00),
        ModelMetadata(id="codestral-latest", name="Codestral", provider="mistral", context_window=32768, input_cost_per_m=0.20, output_cost_per_m=0.60),
    ],
}


def get_model_metadata(provider: str, model_id: str) -> ModelMetadata | None:
    models = PROVIDER_CATALOG.get(provider.lower(), [])
    for m in models:
        if m.id == model_id:
            return m
    return None

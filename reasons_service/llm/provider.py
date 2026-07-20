"""LLM provider factory — returns LangChain ChatModel instances.

Supports Vertex AI (Claude, Gemini) and Ollama for local models.
Auth for Vertex AI: gcloud auth application-default login
"""

from langchain_google_vertexai import ChatVertexAI
from langchain_google_vertexai.model_garden import ChatAnthropicVertex

from reasons_service.config import settings

# Claude on Vertex AI requires us-east5
CLAUDE_LOCATION = "us-east5"


def get_chat_model(model: str | None = None, cached_content: str | None = None):
    """Return a ChatModel instance for the given model name.

    Both Gemini and Claude are accessed through Vertex AI,
    reusing the same GCP project and ADC credentials as agents-python.
    Claude uses ChatAnthropicVertex (Anthropic publisher), Gemini uses ChatVertexAI.

    For Gemini, pass cached_content (cache name from create_context_cache)
    to use server-side context caching.

    Ollama models use the "ollama:" prefix (e.g. "ollama:gemma3:27b").
    Requires: pip install reasons-service[ollama]
    """
    model = model or settings.default_model

    if model.startswith("ollama:"):
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama is required for Ollama models. "
                "Install with: pip install reasons-service[ollama]"
            )
        ollama_model = model[len("ollama:"):]
        return ChatOllama(model=ollama_model, base_url=settings.ollama_host)
    elif "claude" in model:
        return ChatAnthropicVertex(
            model_name=model,
            project=settings.google_cloud_project,
            location=CLAUDE_LOCATION,
            max_tokens=4096,
        )
    elif "gemini" in model:
        kwargs = {}
        if cached_content:
            kwargs["cached_content"] = cached_content
        return ChatVertexAI(
            model_name=model,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown model: {model}")

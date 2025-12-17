from typing import Optional, Any
from enum import Enum
import logging

logger = logging.getLogger("matrix-pdf-bot.llm_factory")

class LLMProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    GENERIC = "generic"

class LLMClientFactory:
    """Factory for creating LLM clients across different providers."""
    
    @staticmethod
    def create_client(
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Create an LLM client for the specified provider.
        
        Args:
            provider: LLM provider name (openai, anthropic, azure, generic)
            api_key: API authentication key
            base_url: Custom endpoint URL (optional)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Configured LLM client instance
            
        Raises:
            ValueError: If provider is not supported
            ImportError: If required provider library is not available
        """
        provider = provider.lower()
        
        if provider == LLMProvider.OPENAI.value:
            return LLMClientFactory._create_openai_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.ANTHROPIC.value:
            return LLMClientFactory._create_anthropic_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.AZURE.value:
            return LLMClientFactory._create_azure_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.GENERIC.value:
            return LLMClientFactory._create_generic_client(api_key, base_url, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def _create_openai_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create OpenAI client."""
        try:
            from openai import AsyncOpenAI
            
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            
            client = AsyncOpenAI(**client_kwargs)
            logger.info(f"✅ OpenAI client created (endpoint: {base_url or 'default'})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")
    
    @staticmethod
    def _create_anthropic_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create Anthropic client."""
        try:
            from anthropic import AsyncAnthropic
            
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            
            client = AsyncAnthropic(**client_kwargs)
            logger.info(f"✅ Anthropic client created (endpoint: {base_url or 'default'})")
            return client
            
        except ImportError:
            raise ImportError("anthropic library not installed. Run: pip install anthropic")
    
    @staticmethod
    def _create_azure_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create Azure OpenAI client."""
        try:
            from openai import AsyncAzureOpenAI
            
            if not base_url:
                raise ValueError("base_url is required for Azure OpenAI")
            
            client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version="2024-02-01"
            )
            logger.info(f"✅ Azure OpenAI client created (endpoint: {base_url})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")
    
    @staticmethod
    def _create_generic_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create generic OpenAI-compatible client."""
        try:
            from openai import AsyncOpenAI
            
            if not base_url:
                raise ValueError("base_url is required for generic OpenAI-compatible APIs")
            
            client = AsyncOpenAI(
                api_key=api_key or "not-required",  # Some local APIs don't need keys
                base_url=base_url
            )
            logger.info(f"✅ Generic OpenAI-compatible client created (endpoint: {base_url})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")

    @staticmethod
    def validate_provider(provider: str) -> bool:
        """Validate if provider is supported."""
        return provider.lower() in [p.value for p in LLMProvider]

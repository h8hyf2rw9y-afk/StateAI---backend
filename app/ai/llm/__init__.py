"""
Provider-agnostic LLM abstraction. Every agent in app/ai/ depends on
LLMProvider (base.py) and errors.py only — never on a specific vendor SDK.
AnthropicProvider is the only implementation today; adding
OpenAIProvider/OllamaProvider/HuggingFaceProvider later means adding
another class here plus a case in factory.py, not touching any agent.
"""

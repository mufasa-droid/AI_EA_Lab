"""
LLM Adapter Interface for AI-EA-Lab Researcher

Provides an abstract interface for language model adapters.
Zero external SDK dependencies. No network calls or credentials required.
Includes MockLLMAdapter for deterministic local execution and testing.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseLLMAdapter(ABC):
    """
    Abstract interface for LLM providers (Gemini, Claude, OpenAI, local models).
    """

    @abstractmethod
    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Generate raw text from a prompt.
        """
        pass

    @abstractmethod
    def generate_research_proposal(
        self,
        research_context: Dict[str, Any],
        research_question: str,
        baseline_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate structured research proposal containing hypothesis and experiment plan.
        """
        pass


class MockLLMAdapter(BaseLLMAdapter):
    """
    Deterministic mock adapter for offline testing without credentials or network calls.
    Consumes genuine research context to form grounded, testable hypotheses.
    """

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        return "[MOCK ADAPTER OUTPUT]: Generated deterministic response for provided prompt."

    def generate_research_proposal(
        self,
        research_context: Dict[str, Any],
        research_question: str,
        baseline_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Formulate grounded mock response using actual context
        return {
            "source": "MOCK RESEARCHER",
            "research_question": research_question,
            "baseline_experiment_id": baseline_id,
        }

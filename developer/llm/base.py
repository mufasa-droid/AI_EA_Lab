"""
LLM / Developer Adapter Interface for AI-EA-Lab Developer

Provides an extensible interface for candidate code generation adapters.
Zero external SDK dependencies. No network calls or credentials required.
Includes MockDeveloperAdapter for deterministic local execution and testing.
"""
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseDeveloperAdapter(ABC):
    """
    Abstract interface for AI Developer code generation adapters
    (Local models, Gemini, Claude, OpenAI, or Mock).
    """

    @abstractmethod
    def develop_candidate(
        self,
        plan: Dict[str, Any],
        baseline_source: str,
    ) -> Dict[str, Any]:
        """
        Generates candidate MQL5 source code strictly implementing authorized changes
        specified in the human-approved experiment plan.
        """
        pass


class MockDeveloperAdapter(BaseDeveloperAdapter):
    """
    Deterministic mock adapter for offline testing without credentials or network calls.
    Applies only the authorized parameter adjustments to MQL5 source code defaults.
    """

    def develop_candidate(
        self,
        plan: Dict[str, Any],
        baseline_source: str,
    ) -> Dict[str, Any]:
        """
        Deterministically modifies only authorized input parameters in baseline source.
        Preserves all comments, formatting, and non-targeted code.
        """
        changes = plan.get("changes_under_test", [])
        modified_source = baseline_source
        applied_changes = []

        for chg in changes:
            var_name = chg.get("variable")
            target_val = str(chg.get("target_value"))

            # Pattern matching: input <type> <var_name> = <val>;
            pattern = re.compile(
                rf"^(\s*input\s+[a-zA-Z0-9_]+\s+{re.escape(var_name)}\s*=\s*)([^;]+)(;.*)$",
                re.MULTILINE
            )

            match = pattern.search(modified_source)
            if match:
                prefix = match.group(1)
                old_val = match.group(2).strip()
                suffix = match.group(3)
                replacement = f"{prefix}{target_val}{suffix}"
                modified_source = modified_source[:match.start()] + replacement + modified_source[match.end():]
                applied_changes.append({
                    "variable": var_name,
                    "before": old_val,
                    "after": target_val,
                })

        return {
            "source": "MOCK DEVELOPER",
            "modified_source": modified_source,
            "applied_changes": applied_changes,
            "rationale": "Deterministic parameter replacement applied according to authorized plan.",
        }

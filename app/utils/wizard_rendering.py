"""
Shared utilities for wizard step rendering to avoid code duplication.
"""

from typing import Any, List

from app.models import WizardStep


class WizardStepAdapter:
    """
    Lightweight adapter that exposes the subset of frontmatter.Post API
    used by wizard rendering functions: `.content` property and `.get()`.
    
    This replaces the duplicated _RowAdapter classes throughout the codebase.
    """

    __slots__ = ("content", "_require")

    def __init__(self, row: WizardStep):
        self.content = row.markdown
        # Mirror frontmatter key `require` from DB boolean
        self._require = bool(getattr(row, "require_interaction", False))

    def get(self, key: str, default: Any = None) -> Any:
        """Get attribute value, mimicking frontmatter.Post.get()."""
        if key == "require":
            return self._require
        return default

    def __iter__(self):
        """Make adapter iterable for compatibility."""
        return iter([self])


def adapt_wizard_steps(steps: List[WizardStep]) -> List[WizardStepAdapter]:
    """
    Convert a list of WizardStep models to WizardStepAdapter instances.
    
    Args:
        steps: List of WizardStep database models
        
    Returns:
        List of WizardStepAdapter instances for rendering
    """
    return [WizardStepAdapter(step) for step in steps]


def get_wizard_step_context(
    steps: List[WizardStep], 
    idx: int, 
    settings_context: dict,
    server_type: str = None
) -> dict:
    """
    Get common context data for wizard step rendering.
    
    Args:
        steps: List of WizardStep models
        idx: Current step index
        settings_context: Settings context dictionary
        server_type: Optional server type for context
        
    Returns:
        Dictionary with common template context
    """
    if not steps:
        return {}
    
    # Ensure index is within bounds
    idx = max(0, min(idx, len(steps) - 1))
    
    # Get current step
    current_step = steps[idx]
    
    # Check interaction requirement
    require_interaction = bool(getattr(current_step, "require_interaction", False))
    
    return {
        "idx": idx,
        "max_idx": len(steps) - 1,
        "current_step": current_step,
        "server_type": server_type or current_step.server_type,
        "require_interaction": require_interaction,
        "total_steps": len(steps),
    }


def validate_wizard_step_index(steps: List[WizardStep], idx: int) -> int:
    """
    Validate and clamp wizard step index to valid range.
    
    Args:
        steps: List of WizardStep models
        idx: Requested step index
        
    Returns:
        Valid step index within bounds
    """
    if not steps:
        return 0
    
    return max(0, min(idx, len(steps) - 1))


def get_timing_display_name(timing: str) -> str:
    """
    Get human-readable display name for timing value.

    Args:
        timing: Timing value ("pre_invite" or "post_invite")

    Returns:
        Human-readable display name
    """
    timing_names = {
        "pre_invite": "Before Invite Acceptance",
        "post_invite": "After Invite Acceptance",
    }

    return timing_names.get(timing, timing.replace("_", " ").title())


def get_timing_icon_class(timing: str) -> str:
    """
    Get CSS icon class for timing value.

    Args:
        timing: Timing value ("pre_invite" or "post_invite")

    Returns:
        CSS class for timing icon
    """
    timing_icons = {
        "pre_invite": "text-blue-600 dark:text-blue-400",
        "post_invite": "text-green-600 dark:text-green-400",
    }

    return timing_icons.get(timing, "text-gray-600 dark:text-gray-400")


def group_steps_by_timing(steps: List[WizardStep]) -> dict[str, List[WizardStep]]:
    """
    Group wizard steps by timing value.
    
    Args:
        steps: List of WizardStep models
        
    Returns:
        Dictionary mapping timing values to lists of steps
    """
    grouped = {}
    
    for step in steps:
        timing = getattr(step, "timing", "after_invite_acceptance")
        if timing not in grouped:
            grouped[timing] = []
        grouped[timing].append(step)
    
    return grouped


def get_navigation_context(
    idx: int, 
    max_idx: int, 
    require_interaction: bool = False
) -> dict:
    """
    Get navigation context for wizard step templates.
    
    Args:
        idx: Current step index
        max_idx: Maximum step index
        require_interaction: Whether current step requires interaction
        
    Returns:
        Dictionary with navigation context
    """
    return {
        "has_previous": idx > 0,
        "has_next": idx < max_idx,
        "is_last_step": idx == max_idx,
        "can_proceed": not require_interaction,
        "previous_idx": max(0, idx - 1),
        "next_idx": min(max_idx, idx + 1),
    }

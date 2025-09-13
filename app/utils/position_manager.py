"""
Position management utilities for handling ordered sequences with unique constraints.

This module provides transaction-safe utilities for reordering items that have
unique constraints on position fields, preventing SQLite UNIQUE constraint violations
during batch updates.
"""

from typing import Any, Protocol, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session


class PositionedItem(Protocol):
    """Protocol for items that have a position field."""

    id: Any
    position: int


T = TypeVar("T", bound=PositionedItem)


class PositionManager:
    """
    Transaction-safe position manager for ordered sequences.

    This class provides methods to safely reorder items that have unique constraints
    on their position field, using a three-phase approach to prevent constraint violations:

    1. Move all items to temporary negative positions
    2. Assign final positions to reordered items
    3. Assign final positions to remaining items
    """

    def __init__(self, session: Any):  # Accept any session type
        self.session = session

    def reorder_items(
        self,
        items_to_reorder: list[T],
        other_items: list[T] | None = None,
        start_position: int = 0,
    ) -> None:
        """
        Safely reorder a list of items with unique position constraints.

        Args:
            items_to_reorder: List of items in their desired order
            other_items: Optional list of other items that should be placed after the reordered items
            start_position: Starting position for the reordered items (default: 0)
        """
        if other_items is None:
            other_items = []

        # Phase 1: Move all items to temporary negative positions to avoid conflicts
        self._move_to_temporary_positions(items_to_reorder, other_items)

        # Phase 2: Set final positions for reordered items
        for i, item in enumerate(items_to_reorder):
            item.position = start_position + i

        # Phase 3: Place other items after the reordered ones
        next_position = start_position + len(items_to_reorder)
        for item in other_items:
            item.position = next_position
            next_position += 1

        self.session.flush()

    def _move_to_temporary_positions(
        self, items_to_reorder: list[T], other_items: list[T]
    ) -> None:
        """Move all items to temporary negative positions to avoid constraint violations."""
        # Move other items to very negative positions first
        for i, item in enumerate(other_items):
            item.position = -(1000 + i)

        # Move items being reordered to temporary negative positions
        for i, item in enumerate(items_to_reorder):
            item.position = -(i + 1)

        self.session.flush()

    def move_item_to_position(
        self, item: T, new_position: int, constraint_fields: dict | None = None
    ) -> None:
        """
        Move a single item to a new position, handling constraint conflicts.

        Args:
            item: The item to move
            new_position: The desired new position
            constraint_fields: Optional dict of field constraints for finding conflicting items
        """
        if constraint_fields is None:
            constraint_fields = {}

        # Move to temporary position first
        item.position = -999
        self.session.flush()

        # Set final position
        item.position = new_position
        self.session.flush()

    def close_position_gap(self, items: list[T], gap_position: int) -> None:
        """
        Close a gap in positions by moving items down.

        Args:
            items: List of items that need to be moved to close the gap
            gap_position: The position where the gap occurred
        """
        if not items:
            return

        # Phase 1: Move to temporary negative positions
        for i, item in enumerate(items):
            item.position = -(i + 1)
        self.session.flush()

        # Phase 2: Set final positions starting from gap_position
        for i, item in enumerate(items):
            item.position = gap_position + i
        self.session.flush()

    def normalize_positions(self, items: list[T], start_position: int = 0) -> None:
        """
        Normalize positions to be sequential starting from start_position.

        This is useful for cleaning up gaps in positions that may have occurred
        due to deletions or other operations.

        Args:
            items: List of items to normalize (should be in desired order)
            start_position: Starting position (default: 0)
        """
        # Phase 1: Move to temporary negative positions
        for i, item in enumerate(items):
            item.position = -(i + 1)
        self.session.flush()

        # Phase 2: Set sequential positions
        for i, item in enumerate(items):
            item.position = start_position + i
        self.session.flush()

    @staticmethod
    def get_max_position(
        session: Session,
        model_class: type[PositionedItem],
        constraint_fields: dict | None = None,
    ) -> int | None:
        """
        Get the maximum position for items matching the given constraints.

        Args:
            session: SQLAlchemy session
            model_class: The model class to query
            constraint_fields: Optional dict of field constraints

        Returns:
            Maximum position or None if no items exist
        """
        stmt = select(func.max(model_class.position))

        if constraint_fields:
            for field_name, field_value in constraint_fields.items():
                field = getattr(model_class, field_name)
                stmt = stmt.where(field == field_value)

        return session.execute(stmt).scalar()

    @staticmethod
    def get_next_position(
        session: Session, model_class: type, constraint_fields: dict | None = None
    ) -> int:
        """
        Get the next available position for items matching the given constraints.

        Args:
            session: SQLAlchemy session
            model_class: The model class to query
            constraint_fields: Optional dict of field constraints

        Returns:
            Next available position (max + 1, or 0 if no items exist)
        """
        max_pos = PositionManager.get_max_position(
            session, model_class, constraint_fields
        )
        return (max_pos if max_pos is not None else -1) + 1


class WizardStepPositionManager(PositionManager):
    """
    Specialized position manager for WizardStep items.

    This class provides WizardStep-specific position management methods that handle
    the unique constraint on (server_type, phase, position).
    """

    def reorder_wizard_steps(
        self,
        steps_to_reorder: list[Any],  # List of WizardStep objects
        server_type: str,
        phase: Any,  # WizardPhase enum
        other_steps: list[Any] | None = None,
    ) -> None:
        """
        Safely reorder wizard steps within a specific server_type and phase.

        Args:
            steps_to_reorder: List of WizardStep objects in desired order
            server_type: Server type constraint
            phase: Phase constraint (WizardPhase enum)
            other_steps: Optional list of other steps in the same phase
        """
        self.reorder_items(steps_to_reorder, other_steps or [])

    def move_step_to_phase(
        self,
        step: Any,  # WizardStep object
        new_phase: Any,  # WizardPhase enum
        remaining_steps_in_old_phase: Any = None,  # Accept any sequence type
        old_position: int | None = None,
    ) -> None:
        """
        Move a wizard step to a different phase, handling position conflicts.

        Args:
            step: The WizardStep to move
            new_phase: Target phase (WizardPhase enum)
            remaining_steps_in_old_phase: Steps that need position adjustment in old phase
            old_position: Original position of the step (for gap closing)
        """
        from app.models import WizardStep  # Import here to avoid circular imports

        # Get next position in new phase
        constraint_fields = {"server_type": step.server_type, "phase": new_phase}
        next_pos = self.get_next_position(self.session, WizardStep, constraint_fields)

        # Move step to new phase with safe positioning
        step.position = -999  # Temporary position
        step.phase = new_phase
        self.session.flush()

        step.position = next_pos
        self.session.flush()

        # Close gap in old phase if needed
        if remaining_steps_in_old_phase and old_position is not None:
            # Convert to list if needed and normalize positions
            steps_list = list(remaining_steps_in_old_phase)
            if steps_list:
                for i, remaining_step in enumerate(steps_list):
                    remaining_step.position = -(i + 1)  # Temporary positions
                self.session.flush()

                for i, remaining_step in enumerate(steps_list):
                    remaining_step.position = old_position + i  # Final positions
                self.session.flush()

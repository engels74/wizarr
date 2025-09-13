"""
Service for managing wizard steps based on timing (pre/post invite acceptance).
"""

from typing import List

from app.models import Invitation, WizardStep


def has_pre_invite_steps_for_invitation(invitation: Invitation) -> bool:
    """
    Check if an invitation has any pre-invite wizard steps.
    
    Args:
        invitation: The invitation to check
        
    Returns:
        bool: True if pre-invite steps exist for any of the invitation's servers
    """
    if not invitation or not invitation.servers:
        return False
    
    # Get all server types for this invitation
    server_types = [server.server_type for server in invitation.servers]
    
    # Check if any pre-invite steps exist for these server types
    pre_steps_count = (
        WizardStep.query
        .filter(
            WizardStep.server_type.in_(server_types),
            WizardStep.timing == "pre_invite"
        )
        .count()
    )
    
    return pre_steps_count > 0


def get_pre_invite_steps_for_invitation(invitation: Invitation) -> List[WizardStep]:
    """
    Get all pre-invite wizard steps for an invitation.
    
    Args:
        invitation: The invitation to get steps for
        
    Returns:
        List[WizardStep]: Ordered list of pre-invite steps for the invitation's servers
    """
    if not invitation or not invitation.servers:
        return []
    
    # Get all server types for this invitation
    server_types = [server.server_type for server in invitation.servers]
    
    # Get pre-invite steps for these server types, ordered by server_type and position
    steps = (
        WizardStep.query
        .filter(
            WizardStep.server_type.in_(server_types),
            WizardStep.timing == "pre_invite"
        )
        .order_by(WizardStep.server_type, WizardStep.position)
        .all()
    )
    
    return steps


def get_post_invite_steps_for_invitation(invitation: Invitation) -> List[WizardStep]:
    """
    Get all post-invite wizard steps for an invitation.
    
    Args:
        invitation: The invitation to get steps for
        
    Returns:
        List[WizardStep]: Ordered list of post-invite steps for the invitation's servers
    """
    if not invitation or not invitation.servers:
        return []
    
    # Get all server types for this invitation
    server_types = [server.server_type for server in invitation.servers]
    
    # Get post-invite steps for these server types, ordered by server_type and position
    steps = (
        WizardStep.query
        .filter(
            WizardStep.server_type.in_(server_types),
            WizardStep.timing == "post_invite"
        )
        .order_by(WizardStep.server_type, WizardStep.position)
        .all()
    )
    
    return steps


def get_steps_by_timing(server_type: str, timing: str) -> List[WizardStep]:
    """
    Get wizard steps for a specific server type and timing.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        timing: The timing ('pre_invite' or 'post_invite')
        
    Returns:
        List[WizardStep]: Ordered list of steps for the server type and timing
    """
    steps = (
        WizardStep.query
        .filter_by(server_type=server_type, timing=timing)
        .order_by(WizardStep.position)
        .all()
    )
    
    return steps


def get_pre_invite_steps_by_server_type(server_type: str) -> List[WizardStep]:
    """
    Get pre-invite wizard steps for a specific server type.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        
    Returns:
        List[WizardStep]: Ordered list of pre-invite steps for the server type
    """
    return get_steps_by_timing(server_type, "pre_invite")


def get_post_invite_steps_by_server_type(server_type: str) -> List[WizardStep]:
    """
    Get post-invite wizard steps for a specific server type.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        
    Returns:
        List[WizardStep]: Ordered list of post-invite steps for the server type
    """
    return get_steps_by_timing(server_type, "post_invite")


def has_steps_for_timing(server_type: str, timing: str) -> bool:
    """
    Check if a server type has any steps for a specific timing.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        timing: The timing ('pre_invite' or 'post_invite')
        
    Returns:
        bool: True if steps exist for the server type and timing
    """
    count = (
        WizardStep.query
        .filter_by(server_type=server_type, timing=timing)
        .count()
    )
    
    return count > 0


def get_all_server_types_with_pre_invite_steps() -> List[str]:
    """
    Get all server types that have pre-invite steps.
    
    Returns:
        List[str]: List of server types that have pre-invite steps
    """
    from sqlalchemy import distinct
    
    server_types = (
        WizardStep.query
        .with_entities(distinct(WizardStep.server_type))
        .filter_by(timing="pre_invite")
        .all()
    )
    
    return [server_type[0] for server_type in server_types]


def get_all_server_types_with_post_invite_steps() -> List[str]:
    """
    Get all server types that have post-invite steps.
    
    Returns:
        List[str]: List of server types that have post-invite steps
    """
    from sqlalchemy import distinct
    
    server_types = (
        WizardStep.query
        .with_entities(distinct(WizardStep.server_type))
        .filter_by(timing="post_invite")
        .all()
    )
    
    return [server_type[0] for server_type in server_types]


def get_step_count_by_timing(server_type: str, timing: str) -> int:
    """
    Get the count of steps for a specific server type and timing.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        timing: The timing ('pre_invite' or 'post_invite')
        
    Returns:
        int: Number of steps for the server type and timing
    """
    return (
        WizardStep.query
        .filter_by(server_type=server_type, timing=timing)
        .count()
    )


def get_next_position_for_timing(server_type: str, timing: str) -> int:
    """
    Get the next available position for a new step with specific server type and timing.
    
    Args:
        server_type: The server type (e.g., 'plex', 'jellyfin')
        timing: The timing ('pre_invite' or 'post_invite')
        
    Returns:
        int: Next available position (0-based)
    """
    from sqlalchemy import func
    
    max_position = (
        WizardStep.query
        .with_entities(func.max(WizardStep.position))
        .filter_by(server_type=server_type, timing=timing)
        .scalar()
    )
    
    return (max_position or -1) + 1

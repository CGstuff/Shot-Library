"""Qt Models for Shot Library v2"""

from .shot_list_model import ShotListModel, ShotRole
from .shot_filter_proxy_model import ShotFilterProxyModel

# Legacy aliases for backward compatibility during transition
# These should be removed once all code is migrated to shot-specific models
AnimationListModel = ShotListModel
AnimationRole = ShotRole
AnimationFilterProxyModel = ShotFilterProxyModel

__all__ = [
    'ShotListModel',
    'ShotRole',
    'ShotFilterProxyModel',
    # Legacy exports
    'AnimationListModel',
    'AnimationRole',
    'AnimationFilterProxyModel',
]

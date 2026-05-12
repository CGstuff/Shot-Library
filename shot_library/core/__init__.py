"""Core business logic for Shot Library"""

from .shot_indexer import (
    ShotStatus,
    ParsedShotIdentity,
    DiscoveredShot,
    ShotIndexer,
    generate_editorial_order,
)
from .folder_schema_parser import (
    HierarchyLevel,
    SchemaConfig,
    ParsedPath,
    FolderSchemaParser,
    SCHEMA_PRESETS,
    get_preset,
)
from .folder_observer import (
    ChangeType,
    FileSystemChange,
    FolderObserver,
)
from .playblast_indexer import (
    PlayblastMetadata,
    DiscoveredPlayblast,
    PlayblastIndexer,
)
# New unified media abstractions
from .media_types import (
    MediaType,
    MediaConfig,
    get_media_config,
    get_all_media_configs,
    get_media_type_by_folder,
    get_media_type_by_prefix,
)
from .media_indexer import (
    MediaMetadata,
    DiscoveredMedia,
    MediaIndexer,
    create_playblast_indexer,
    create_lookdev_indexer,
    create_render_indexer,
)
from .editorial_order import (
    EditorialComponents,
    EDITORIAL_PATTERNS,
    UNPARSEABLE_ORDER,
    extract_editorial_components,
    generate_editorial_order_string,
    get_editorial_order,
    compare_editorial_order,
)
from .shot_version_parser import (
    ShotVersionInfo,
    parse_shot_version,
    generate_version_group_id,
    group_shots_by_version,
    find_latest_in_group,
    mark_latest_versions,
)
from .render_indexer import (
    DiscoveredRender,
    RenderIndexer,
    get_render_indexer,
)

__all__ = [
    # Shot Indexer
    'ShotStatus',
    'ParsedShotIdentity',
    'DiscoveredShot',
    'ShotIndexer',
    'generate_editorial_order',
    # Folder Schema Parser
    'HierarchyLevel',
    'SchemaConfig',
    'ParsedPath',
    'FolderSchemaParser',
    'SCHEMA_PRESETS',
    'get_preset',
    # Folder Observer
    'ChangeType',
    'FileSystemChange',
    'FolderObserver',
    # Playblast Indexer
    'PlayblastMetadata',
    'DiscoveredPlayblast',
    'PlayblastIndexer',
    # Editorial Order
    'EditorialComponents',
    'EDITORIAL_PATTERNS',
    'UNPARSEABLE_ORDER',
    'extract_editorial_components',
    'generate_editorial_order_string',
    'get_editorial_order',
    'compare_editorial_order',
    # Shot Version Parser
    'ShotVersionInfo',
    'parse_shot_version',
    'generate_version_group_id',
    'group_shots_by_version',
    'find_latest_in_group',
    'mark_latest_versions',
    # Media Types (unified abstraction)
    'MediaType',
    'MediaConfig',
    'get_media_config',
    'get_all_media_configs',
    'get_media_type_by_folder',
    'get_media_type_by_prefix',
    # Media Indexer (unified)
    'MediaMetadata',
    'DiscoveredMedia',
    'MediaIndexer',
    'create_playblast_indexer',
    'create_lookdev_indexer',
    'create_render_indexer',
    # Render Indexer (folder-based versioning)
    'DiscoveredRender',
    'RenderIndexer',
    'get_render_indexer',
]

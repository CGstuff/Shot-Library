"""
Shot Library Protocol - Single source of truth for Desktop↔Blender IPC.

This package defines message types, validation rules, and shared constants
for communication between the Shot Library desktop app and Blender plugin.

Shot Library Note: This is a read-only viewer. Animation application messages
have been removed. Only status queries and playblast-related messages are supported.

Architecture:
    Desktop App sends queries → Blender Plugin responds
    Blender Plugin captures playblasts → Desktop App discovers them

Communication Methods:
    1. Socket-based (preferred): Real-time TCP socket (~10-50ms latency)
    2. File-based (fallback): JSON queue files (~100-500ms latency)

Usage - Blender Plugin:
    from ..protocol import validate_message, get_field_value

    # Validate incoming message
    is_valid, error = validate_message(incoming_msg)
    if not is_valid:
        return build_error_response(error)

Sync Strategy:
    The protocol/ directory is copied from shot_library to SL_blender_plugin
    during addon install/update. Both sides read from the same schema.
"""

# Schema definitions
from .schema import (
    FieldDef,
    MessageDef,
    ResponseDef,
    MESSAGE_TYPES,
    RESPONSE_FIELDS,
    APPLY_OPTIONS_SCHEMA,
    get_message_def,
    get_field_def,
)

# Message builders and validators
from .messages import (
    # Core functions
    build_message,
    validate_message,
    validate_options,
    get_field_value,
    normalize_message,

    # Response builders
    build_response,
    build_success_response,
    build_error_response,

    # Exceptions
    ValidationError,
)

# Constants
from .constants import (
    # Queue
    QUEUE_DIR_NAME,
    FALLBACK_QUEUE_DIR,
    QUEUE_FILE_PATTERN,

    # Socket
    DEFAULT_SOCKET_PORT,
    SOCKET_HOST,
    SOCKET_PORT_ENV_VAR,
    SOCKET_CONNECT_TIMEOUT,
    SOCKET_RECEIVE_TIMEOUT,
    SOCKET_COMMAND_TIMEOUT,
    MAX_CONNECTION_RETRIES,
    RETRY_DELAY_MS,

    # Enums
    MessageStatus,
    RigType,
    CommandType,

    # Polling
    SOCKET_POLL_INTERVAL_MS,
    QUEUE_TIME_BUDGET_MS,
    MAX_HEAVY_COMMANDS_PER_TICK,
    HEAVY_COMMANDS,

    # Version
    PROTOCOL_VERSION,
)


__all__ = [
    # Schema
    'FieldDef',
    'MessageDef',
    'ResponseDef',
    'MESSAGE_TYPES',
    'RESPONSE_FIELDS',
    'APPLY_OPTIONS_SCHEMA',
    'get_message_def',
    'get_field_def',

    # Message functions
    'build_message',
    'validate_message',
    'validate_options',
    'get_field_value',
    'normalize_message',
    'build_response',
    'build_success_response',
    'build_error_response',
    'ValidationError',

    # Constants
    'QUEUE_DIR_NAME',
    'FALLBACK_QUEUE_DIR',
    'QUEUE_FILE_PATTERN',
    'DEFAULT_SOCKET_PORT',
    'SOCKET_HOST',
    'SOCKET_PORT_ENV_VAR',
    'SOCKET_CONNECT_TIMEOUT',
    'SOCKET_RECEIVE_TIMEOUT',
    'SOCKET_COMMAND_TIMEOUT',
    'MAX_CONNECTION_RETRIES',
    'RETRY_DELAY_MS',
    'MessageStatus',
    'RigType',
    'CommandType',
    'SOCKET_POLL_INTERVAL_MS',
    'QUEUE_TIME_BUDGET_MS',
    'MAX_HEAVY_COMMANDS_PER_TICK',
    'HEAVY_COMMANDS',
    'PROTOCOL_VERSION',
]

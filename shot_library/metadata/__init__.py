"""
Shot Library Metadata - Field registry and validation.

This package provides a single source of truth for all shot metadata fields:
- Field type definitions
- Validation rules
- UI generation hints
- Category organization

Usage:
    from shot_library.metadata import SHOT_FIELDS, get_field

    # Get field definition
    field = get_field('status')
    print(f"Type: {field.field_type}, Choices: {field.choices}")

    # Validate a value
    from shot_library.metadata import validate_field
    is_valid, error = validate_field('status', 'wip')
"""

from .registry import (
    # Types
    FieldDef,
    FieldType,
    FieldCategory,

    # Registry
    SHOT_FIELDS,

    # Functions
    get_field,
    get_fields_by_category,
    get_required_fields,
    get_sortable_fields,
    get_card_fields,
    get_editable_fields,
    validate_field,
    validate_shot,
)

__all__ = [
    'FieldDef',
    'FieldType',
    'FieldCategory',
    'SHOT_FIELDS',
    'get_field',
    'get_fields_by_category',
    'get_required_fields',
    'get_sortable_fields',
    'get_card_fields',
    'get_editable_fields',
    'validate_field',
    'validate_shot',
]

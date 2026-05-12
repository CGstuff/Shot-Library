"""
Render Settings Manager - Shared render settings utilities

Consolidates duplicate code from SL_playblast.py and SL_lookdev.py:
- _store_all_settings() / _restore_all_settings() - 95% identical
- _configure_render() - 90% identical (video output setup)
"""

import bpy
from pathlib import Path
from typing import Dict, Optional


def store_render_settings(context, include_overlay: bool = True) -> Dict:
    """
    Store all render settings for restoration.

    Args:
        context: Blender context
        include_overlay: Whether to include overlay settings (for playblast)

    Returns:
        Dictionary of stored settings
    """
    scene = context.scene
    space = context.space_data if hasattr(context, 'space_data') else None

    settings = {
        # Basic render settings
        'filepath': scene.render.filepath,
        'file_format': scene.render.image_settings.file_format,
        'color_mode': scene.render.image_settings.color_mode,
        'color_depth': scene.render.image_settings.color_depth,
        'resolution_x': scene.render.resolution_x,
        'resolution_y': scene.render.resolution_y,
        'resolution_percentage': scene.render.resolution_percentage,
        'film_transparent': scene.render.film_transparent,
        'use_file_extension': scene.render.use_file_extension,
        'use_stamp': scene.render.use_stamp,
        'stamp_font_size': scene.render.stamp_font_size,
    }

    # FFMPEG settings (pre-Blender 5.0)
    if bpy.app.version < (5, 0, 0):
        if scene.render.image_settings.file_format == 'FFMPEG':
            settings['ffmpeg_format'] = scene.render.ffmpeg.format
            settings['ffmpeg_codec'] = scene.render.ffmpeg.codec
            settings['ffmpeg_gopsize'] = scene.render.ffmpeg.gopsize
            settings['ffmpeg_audio'] = scene.render.ffmpeg.audio_codec

    # Blender 5.0+ media type
    if bpy.app.version >= (5, 0, 0):
        settings['media_type'] = scene.render.image_settings.media_type
        settings['ffmpeg_format'] = scene.render.ffmpeg.format
        settings['ffmpeg_codec'] = scene.render.ffmpeg.codec

    # Viewport shading mode (for EEVEE lookdev)
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    settings['viewport_shading_type'] = sp.shading.type
            break

    # Cycles-specific settings
    if scene.render.engine == 'CYCLES':
        settings['cycles_samples'] = scene.cycles.samples
        settings['cycles_use_adaptive_sampling'] = scene.cycles.use_adaptive_sampling
        if hasattr(scene.cycles, 'adaptive_threshold'):
            settings['cycles_adaptive_threshold'] = scene.cycles.adaptive_threshold

    # EEVEE-specific settings
    if scene.render.engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
        if hasattr(scene.eevee, 'taa_render_samples'):
            settings['eevee_taa_render_samples'] = scene.eevee.taa_render_samples
        if hasattr(scene.eevee, 'taa_samples'):
            settings['eevee_taa_samples'] = scene.eevee.taa_samples

    # Overlay settings (comprehensive like reference plugin)
    if include_overlay and space and hasattr(space, 'overlay'):
        overlay = space.overlay
        settings['show_overlays'] = overlay.show_overlays
        settings['show_bones'] = overlay.show_bones
        settings['show_extras'] = overlay.show_extras
        settings['show_floor'] = overlay.show_floor
        settings['show_axis_x'] = overlay.show_axis_x
        settings['show_axis_y'] = overlay.show_axis_y
        settings['show_axis_z'] = overlay.show_axis_z
        settings['show_text'] = overlay.show_text
        settings['show_cursor'] = overlay.show_cursor
        settings['show_annotation'] = overlay.show_annotation
        settings['show_relationship_lines'] = overlay.show_relationship_lines
        settings['show_outline_selected'] = overlay.show_outline_selected
        settings['show_motion_paths'] = overlay.show_motion_paths
        settings['show_object_origins'] = overlay.show_object_origins
        settings['show_wireframes'] = overlay.show_wireframes
        settings['show_face_orientation'] = overlay.show_face_orientation

        if bpy.app.version >= (2, 90, 0):
            settings['show_stats'] = overlay.show_stats

    if include_overlay and space and hasattr(space, 'show_reconstruction'):
        settings['show_reconstruction'] = space.show_reconstruction

    return settings


def restore_render_settings(context, settings: Dict, include_overlay: bool = True):
    """
    Restore all original settings.

    Args:
        context: Blender context
        settings: Dictionary of stored settings
        include_overlay: Whether to restore overlay settings
    """
    if not settings:
        return

    scene = context.scene
    space = context.space_data if hasattr(context, 'space_data') else None

    # Basic render settings
    scene.render.filepath = settings['filepath']
    scene.render.resolution_x = settings['resolution_x']
    scene.render.resolution_y = settings['resolution_y']
    scene.render.resolution_percentage = settings['resolution_percentage']
    scene.render.film_transparent = settings['film_transparent']
    scene.render.use_file_extension = settings['use_file_extension']
    scene.render.use_stamp = settings['use_stamp']
    scene.render.stamp_font_size = settings['stamp_font_size']

    # Blender 5.0+ - restore media_type FIRST (before file_format)
    if bpy.app.version >= (5, 0, 0):
        if 'media_type' in settings:
            scene.render.image_settings.media_type = settings['media_type']
        if 'ffmpeg_format' in settings:
            scene.render.ffmpeg.format = settings['ffmpeg_format']
            scene.render.ffmpeg.codec = settings['ffmpeg_codec']

    # Now restore file_format (after media_type is set correctly)
    scene.render.image_settings.file_format = settings['file_format']
    scene.render.image_settings.color_mode = settings['color_mode']
    scene.render.image_settings.color_depth = settings['color_depth']

    # FFMPEG settings (pre-Blender 5.0)
    if bpy.app.version < (5, 0, 0):
        if 'ffmpeg_format' in settings:
            scene.render.ffmpeg.format = settings['ffmpeg_format']
            scene.render.ffmpeg.codec = settings['ffmpeg_codec']
            scene.render.ffmpeg.gopsize = settings['ffmpeg_gopsize']
            scene.render.ffmpeg.audio_codec = settings['ffmpeg_audio']

    # Cycles-specific settings
    if 'cycles_samples' in settings:
        scene.cycles.samples = settings['cycles_samples']
    if 'cycles_use_adaptive_sampling' in settings:
        scene.cycles.use_adaptive_sampling = settings['cycles_use_adaptive_sampling']
    if 'cycles_adaptive_threshold' in settings and hasattr(scene.cycles, 'adaptive_threshold'):
        scene.cycles.adaptive_threshold = settings['cycles_adaptive_threshold']

    # EEVEE-specific settings
    if 'eevee_taa_render_samples' in settings and hasattr(scene.eevee, 'taa_render_samples'):
        scene.eevee.taa_render_samples = settings['eevee_taa_render_samples']
    if 'eevee_taa_samples' in settings and hasattr(scene.eevee, 'taa_samples'):
        scene.eevee.taa_samples = settings['eevee_taa_samples']

    # Restore viewport shading mode
    if 'viewport_shading_type' in settings:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for sp in area.spaces:
                    if sp.type == 'VIEW_3D':
                        sp.shading.type = settings['viewport_shading_type']
                break

    # Overlay settings
    if include_overlay and space and hasattr(space, 'overlay'):
        overlay = space.overlay
        if 'show_overlays' in settings:
            overlay.show_overlays = settings['show_overlays']
        if 'show_bones' in settings:
            overlay.show_bones = settings['show_bones']
        if 'show_extras' in settings:
            overlay.show_extras = settings['show_extras']
        if 'show_floor' in settings:
            overlay.show_floor = settings['show_floor']
        if 'show_axis_x' in settings:
            overlay.show_axis_x = settings['show_axis_x']
        if 'show_axis_y' in settings:
            overlay.show_axis_y = settings['show_axis_y']
        if 'show_axis_z' in settings:
            overlay.show_axis_z = settings['show_axis_z']
        if 'show_text' in settings:
            overlay.show_text = settings['show_text']
        if 'show_cursor' in settings:
            overlay.show_cursor = settings['show_cursor']
        if 'show_annotation' in settings:
            overlay.show_annotation = settings['show_annotation']
        if 'show_relationship_lines' in settings:
            overlay.show_relationship_lines = settings['show_relationship_lines']
        if 'show_outline_selected' in settings:
            overlay.show_outline_selected = settings['show_outline_selected']
        if 'show_motion_paths' in settings:
            overlay.show_motion_paths = settings['show_motion_paths']
        if 'show_object_origins' in settings:
            overlay.show_object_origins = settings['show_object_origins']
        if 'show_wireframes' in settings:
            overlay.show_wireframes = settings['show_wireframes']
        if 'show_face_orientation' in settings:
            overlay.show_face_orientation = settings['show_face_orientation']

        if bpy.app.version >= (2, 90, 0) and 'show_stats' in settings:
            overlay.show_stats = settings['show_stats']

    if include_overlay and space and hasattr(space, 'show_reconstruction'):
        if 'show_reconstruction' in settings:
            space.show_reconstruction = settings['show_reconstruction']


def configure_video_output(context, output_path: Path, quality: str = 'HALF'):
    """
    Configure render settings for video output.

    Args:
        context: Blender context
        output_path: Path for output file
        quality: 'PREVIEW' (25%), 'HALF' (50%), or 'FULL' (100%)
    """
    scene = context.scene

    # Output path
    scene.render.filepath = str(output_path)
    scene.render.use_file_extension = False

    # Configure for video output
    if bpy.app.version >= (5, 0, 0):
        # Blender 5.0+ uses media_type
        scene.render.image_settings.media_type = 'VIDEO'
        scene.render.ffmpeg.format = 'MPEG4'
        scene.render.ffmpeg.codec = 'H264'
    else:
        # Pre-Blender 5.0
        scene.render.image_settings.file_format = 'FFMPEG'
        scene.render.ffmpeg.format = 'MPEG4'
        scene.render.ffmpeg.codec = 'H264'
        scene.render.ffmpeg.gopsize = 18
        scene.render.ffmpeg.audio_codec = 'AAC'

    # Resolution based on quality setting
    if quality == 'PREVIEW':
        scene.render.resolution_percentage = 25
    elif quality == 'HALF':
        scene.render.resolution_percentage = 50
    else:  # FULL
        scene.render.resolution_percentage = 100

    # Force resolution to be divisible by 2 (required for H264)
    res_x = scene.render.resolution_x * scene.render.resolution_percentage // 100
    res_y = scene.render.resolution_y * scene.render.resolution_percentage // 100

    if res_x % 2 != 0:
        scene.render.resolution_x += 1
    if res_y % 2 != 0:
        scene.render.resolution_y += 1

    # Ensure opaque background
    scene.render.film_transparent = False

    # No stamp by default
    scene.render.use_stamp = False


def hide_overlays(context, mode: str = 'ALL'):
    """
    Hide overlays based on mode.

    Args:
        context: Blender context
        mode: 'ALL' (hide all), 'BONES' (hide only bones), 'NONE' (keep visible)
    """
    space = context.space_data if hasattr(context, 'space_data') else None

    if not space or not hasattr(space, 'overlay'):
        return

    overlay = space.overlay

    if mode == 'ALL':
        overlay.show_overlays = False
    elif mode == 'BONES':
        overlay.show_bones = False
    # 'NONE' - keep everything visible


__all__ = [
    'store_render_settings',
    'restore_render_settings',
    'configure_video_output',
    'hide_overlays',
]

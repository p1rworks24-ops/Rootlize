"""English UI message catalog.

Add other locale modules (e.g. ja.py) later and register them in app.i18n.
"""

MESSAGES: dict[str, str] = {
    # Common
    "common.error": "Error",
    "common.warning": "Warning",
    "common.saved": "Saved",
    "common.confirm_delete": "Confirm Delete",
    "common.tag": "Tag",
    "common.browse": "Browse",
    "common.save": "Save",
    "common.copy": "Copy",
    "common.cut": "Cut",
    "common.paste": "Paste",
    "common.delete": "Delete",
    "common.view": "View",
    "common.select_all": "Select All",
    # Navigation / shell
    "nav.home": "Home",
    "nav.images": "Images",
    "nav.organize": "Organize",
    "nav.action": "Organize",  # legacy alias
    "nav.work": "Organize",  # legacy alias
    "nav.tags": "Tags",
    "nav.ai": "AI (Coming Soon)",
    "nav.ai_tooltip": "AI features will be available in a future version.",
    "nav.settings": "Settings",
    "nav.brand": "Screenshot\nManager",
    "shell.screenshot": "Screenshot",
    "shell.screenshot_tooltip": (
        "Minimize this window and open Win+Shift+S to capture a screenshot"
    ),
    "shell.capture.region": "Region Capture",
    "shell.capture.region_tooltip": (
        "Drag to capture any region. Uses the same save folder, filename, and tags."
    ),
    "shell.capture.region_desc": "Drag to select a region",
    "shell.capture.fullscreen": "Full Screen Capture",
    "shell.capture.fullscreen_tooltip": (
        "Capture the entire screen. Uses the same save folder, filename, and tags."
    ),
    "shell.capture.fullscreen_desc": "Capture the entire screen",
    "shell.capture.cycle_tooltip": "Switch capture mode",
    "shell.capture.cycle_label": "Switch mode",
    "shell.save_folder": "Root folder",
    "shell.save_folder_tooltip": "Change the root folder in Settings",
    "shell.save_folder_label": "📂 {name}",
    "shell.save_destination": "Save folder",
    "shell.save_destination_tooltip": (
        "Where new screenshots are saved. Independent from the Images viewing folder."
    ),
    "shell.save_destination_empty": "No folders",
    "shell.save_filename_title": "Save filename",
    "shell.filename_preview_line": "Preview: {name}",
    "shell.filename_preview_example": "e.g. {name}",
    "shell.rule.datetime": "Datetime",
    "shell.rule.sequential": "Sequential",
    "shell.rule.datetime_num": "Datetime + number",
    "shell.rule.custom": "Custom",
    "shell.rule.custom_hint": "Your own pattern",
    "shell.rule.custom_placeholder": "{date}_{time} or Screenshot_{num}",
    "shell.capture_tags": "Save tags",
    "shell.capture_tags_none": "None",
    "shell.capture_tags_tooltip": (
        "Tag applied automatically when a screenshot is saved. "
        "Multi-tag selection can be added later."
    ),
    "shell.capture_tag_add": "Add",
    "shell.capture_tag_create": "New",
    "shell.capture_tag_new_placeholder": "New tag…",
    "shell.filename_template": "Save filename",
    "shell.filename_template_tooltip": (
        "Choose how new screenshots are named."
    ),
    "shell.filename_template_preview": "Saves as: {name}",
    "shell.filename_preset.date_time": "{date}_{time}",
    "shell.filename_preset.folder_num": "{folder}_{num}",
    "shell.filename_preset.screenshot_date_time": "Screenshot_{date}_{time}",
    "shell.filename_preset.date_folder_num": "{date}_{folder}_{num}",
    "shell.filename_preset.testshot_num": "testshot_{num}",
    "shell.filename_preset.custom": "Custom…",
    "shell.filename_custom_title": "Save filename template",
    "shell.filename_custom_prompt": (
        "Enter a save-filename template using {date}, {time}, {folder}, and/or {num}:"
    ),
    "shell.folder": "Folder",
    "shell.current_folder": "Folder",
    "shell.current_folder_tooltip": (
        "Screenshots are saved to this folder. Switch anytime from this list."
    ),
    "shell.current_folder_empty": "No folders",
    "common.undo": "Undo",
    "images.rename_title": "Rename",
    "images.rename_prompt": "New file name:",
    "images.rename_failed": "Failed to rename: {error}",
    "images.rename_exists": "A file with that name already exists.",
    "images.rename_invalid": "Please enter a valid file name.",
    "images.undo_failed": "Failed to undo: {error}",
    "images.undo_empty": "Nothing to undo.",
    # Home
    "home.title": "Home",
    "home.subtitle": "Overview of your screenshot library.",
    "home.current_folder": "Root Folder",  # legacy alias
    "home.root_folder": "Root Folder",
    "home.image_count": "Images & storage",
    "home.root_totals": "{count} images  ·  {size}",
    "home.quick_actions": "Quick Actions",
    "home.open_images": "Open Images",
    "home.settings": "Settings",
    "home.recent": "Recent Images",
    "home.no_recent": "No recent screenshots",
    "home.stats": "Statistics",
    "home.stats_view": "Display by",
    "home.stats_folder": "Folder",
    "home.stats_tag": "Tag",
    "home.stats_by_folder": "Folder",
    "home.stats_by_tag": "Tag",
    "home.stats_hint": (
        "Compare image counts and disk usage. "
        "Use Display by to switch between folder and tag charts."
    ),
    # Sort
    "sort.modified_desc": "Date modified (newest)",
    "sort.modified_asc": "Date modified (oldest)",
    "sort.filename_asc": "Filename (A–Z)",
    "sort.filename_desc": "Filename (Z–A)",
    # View modes
    "view.large": "Large",
    "view.medium": "Medium",
    "view.small": "Small",
    "view.details": "Small",
    # Images page
    "images.title": "Images",
    "images.subtitle": "Browse, search and manage screenshots.",
    "images.refresh": "Refresh",
    "images.search_placeholder": "Search by filename or tag...",
    "images.search": "Search",
    "images.clear": "Clear",
    "images.sort_label": "Sort",
    "images.group_by_label": "Group By",
    "images.group_by_save_failed": "Failed to save group setting: {error}",
    "group_by.none": "None",
    "group_by.date": "Date",
    "group_by.tag": "Tag",
    "group_by.no_tag": "No tags",
    "images.folders": "Viewing folder",
    "images.viewing_folder_hint": "Browsing under {root}",
    "images.save_folder_marker_tooltip": (
        "{name} — Screenshot Save folder (★)"
    ),
    "images.save_folder_star_legend": (
        "★ Save folder — capture destination"
    ),
    "images.collapse_folders": "Collapse viewing folders",
    "images.expand_folders": "Expand viewing folders",
    "images.new_folder": "New Folder",
    "images.new_folder_tooltip": "Create a folder under the screenshot root",
    "images.screenshots": "Screenshots",
    "images.preview": "Preview",
    "images.select_image": "Select an image",
    "images.file_none": "File: <i>None</i>",
    "images.file_name": "File: <b>{name}</b>",
    "images.tags": "Tags",
    "images.open": "Open",
    "images.edit_tags": "Edit Tags",
    "images.tag_add": "Add Tag",
    "images.tag_remove": "Remove Tag",
    "images.tag_none_available": "No tags available",
    "images.tag.mode_existing": "Existing Tag",
    "images.tag.mode_new": "New Tag",
    "images.tag.select_placeholder": "Select a tag...",
    "images.tag.new_placeholder": "New tag name...",
    "images.tag.assign": "Add",
    "images.tag.create_assign": "Add",
    "images.tag.none": "No tags",
    "images.tag.remove_tooltip": "Click to remove tag",
    "images.tag.save_failed": "Failed to save tag: {error}",
    "images.tag.remove_failed": "Failed to remove tag: {error}",
    "images.tag.already_assigned": "This tag is already assigned.",
    "images.load_failed": "Failed to load image",
    "images.folder.new_title": "New Folder",
    "images.folder.new_folder": "New Folder",
    "images.folder.name_prompt": "Folder Name:",
    "images.folder.name_required": "Please enter a folder name.",
    "images.folder.name_invalid": "The folder name contains invalid characters.",
    "images.folder.exists": "A folder with this name already exists.",
    "images.folder.missing": "That folder no longer exists.",
    "images.folder.create_failed": "Failed to create folder: {error}",
    "images.folder.switch_failed": "Failed to switch folder: {error}",
    "images.folder.rename": "Rename",
    "images.folder.rename_title": "Rename Folder",
    "images.folder.rename_prompt": "New folder name:",
    "images.folder.rename_failed": "Failed to rename folder: {error}",
    "images.folder.duplicate": "Duplicate",
    "images.folder.duplicated": 'Duplicated as "{name}".',
    "images.folder.duplicate_failed": "Failed to duplicate folder: {error}",
    "images.folder.delete": "Delete",
    "images.folder.delete_confirm": (
        'Delete folder "{name}"?\n\n'
        "All screenshots and metadata inside it will be removed."
    ),
    "images.folder.delete_last": "You cannot delete the last remaining folder.",
    "images.folder.delete_failed": "Failed to delete folder: {error}",
    "images.sort_save_failed": "Failed to save sort setting: {error}",
    "images.view_save_failed": "Failed to save view setting: {error}",
    "images.paste.title": "Paste",
    "images.paste.failed": "Failed to paste: {error}",
    "images.cut.failed": "Failed to cut: {error}",
    "images.dnd.move_failed": "Failed to move: {error}",
    "images.dnd.copy_failed": "Failed to copy: {error}",
    "images.open_explorer": "Open in Explorer",
    "images.delete_confirm": (
        "Are you sure you want to delete this screenshot?\n\n{name}"
    ),
    "images.delete_confirm_multi": (
        "Are you sure you want to delete {count} screenshots?"
    ),
    "images.delete_failed": "Failed to delete file: {error}",
    "images.file_selected_count": "{count} selected",
    "images.copy_count": "Copy ({count})",
    "images.cut_count": "Cut ({count})",
    "images.delete_count": "Delete ({count})",
    "images.folder_missing_switched": (
        "The previous folder was removed. Switched to \"{name}\"."
    ),
    # Tags page
    "tags.title": "Tags",
    "tags.subtitle": "Create and manage tags.",
    "tags.hint": "Assign tags to images on the Images page.",
    "tags.new_placeholder": "New tag name...",
    "tags.add": "Add",
    "tags.rename": "Rename",
    "tags.delete": "Delete",
    "tags.added_as": 'A tag with that name already existed, so it was added as "{name}".',
    "tags.add_failed": "Failed to add tag: {error}",
    "tags.rename_title": "Rename Tag",
    "tags.rename_prompt": "New tag name:",
    "tags.renamed_as": 'A tag with that name already existed, so it was renamed to "{name}".',
    "tags.rename_failed": "Failed to rename tag: {error}",
    "tags.delete_confirm": (
        'Delete the shared tag "{tag}"?\n'
        "It will also be removed from all images."
    ),
    "tags.delete_failed": "Failed to delete tag: {error}",
    # Organize page (formerly Action / Work)
    "work.title": "Organize",
    "work.subtitle": (
        "Select images, choose an operation, and apply it in bulk."
    ),
    "work.hint": (
        "Select images in the current folder, then apply bulk tag or rename actions."
    ),
    "work.image_list": "Image List",
    "work.folder_label": "Folder",
    "work.selected_heading": "Selected",
    "work.selected_count": "{count} Images",
    "work.operations": "Operations",
    "work.operations_hint": (
        "Choose an operation, then configure it below for the selected images."
    ),
    "work.op_tags": "Tags",
    "work.op_rename": "Rename",
    "work.current_folder": "Folder: {name}",
    "work.current_context": "Folder: {folder}",
    "work.images": "Images",
    "work.view_label": "View",
    "work.clear_selection": "Clear selection",
    "work.bulk_tags": "Bulk Tags",
    "work.bulk_tags_hint": (
        "You can add or remove tags on all selected images at once."
    ),
    "work.tag_add": "Add tag",
    "work.tag_remove": "Remove tag",
    "work.apply_add": "Add to selected",
    "work.apply_remove": "Remove from selected",
    "work.need_selection": "Select one or more images first.",
    "work.tag_add_done": "Added “{tag}” to {count} image(s).",
    "work.tag_remove_done": "Removed “{tag}” from {count} image(s).",
    "work.tag_failed": "Tag operation failed: {error}",
    "work.bulk_rename": "Bulk Rename",
    "work.bulk_rename_hint": (
        "You can rename selected images in capture-date order with sequential numbers."
    ),
    "work.rename_prefix": "Prefix",
    "work.rename_prefix_placeholder": "ScreenShot_test_",
    "work.rename_digits": "Digits (≥ 3)",
    "work.rename_preview_empty": "Select images to preview rename results.",
    "work.rename_preview_more": "…and {count} more",
    "work.apply_rename": "Rename selected",
    "work.rename_prefix_required": "Please enter a rename prefix.",
    "work.rename_conflict": "Target name already exists: {name}",
    "work.rename_confirm": (
        "Rename {count} image(s) with prefix “{prefix}”?\n"
        "Numbers are assigned oldest-first."
    ),
    "work.rename_done": "Renamed {count} image(s).",
    "work.rename_failed": "Bulk rename failed: {error}",
    # Settings page
    "settings.title": "Settings",
    "settings.subtitle": "Configure application preferences.",
    "settings.autosave_hint": (
        "Changes are saved automatically — no Save button needed."
    ),
    "settings.save_folder": "Root Folder",
    "settings.ui": "UI Settings",
    "settings.window_width": "Window width",
    "settings.window_height": "Window height",
    "settings.future_hint": "Future settings (theme, language, etc.) will appear here.",
    "settings.select_directory": "Select Root Directory",
    "settings.path_empty": "Root directory path cannot be empty.",
    "settings.size_invalid": "Window size must be a number.",
    "settings.saved": "Settings saved.",
    "settings.autosaved": "Saved automatically.",
    "settings.save_failed": "Failed to save settings: {error}",
}

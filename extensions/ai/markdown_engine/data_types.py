# markdown_engine/data_types.py
from enum import IntEnum
from dataclasses import dataclass, field
from typing import List, Any

class BlockType(IntEnum):
    PARAGRAPH = 0
    CODE = 1
    LIST_ITEM = 2
    HEADER = 3
    QUOTE = 4
    TABLE = 5
    DIVIDER = 6

class FormatType(IntEnum):
    NORMAL = 0
    BOLD = 1
    ITALIC = 2
    BOLD_ITALIC = 3
    CODE = 4
    STRIKETHROUGH = 5
    LINK = 6

@dataclass
class FormatRange:
    start: int
    length: int
    format_type: FormatType
    data: str = None

class LayoutLine:
    """Helper to store exact geometry of a rendered line for hit-testing"""
    __slots__ = ['text', 'rect', 'fm', 'char_start', 'render_cache'] 

    def __init__(self, text, rect, font_metrics, char_offset_start):
        self.text = text
        self.rect = rect
        self.fm = font_metrics
        self.char_start = char_offset_start
        self.render_cache: List[Any] = None 

class TextBlock:
    """Represents a single block of content"""
    __slots__ = (
        'text', 'type', 'level', 'formatting', 
        'indent_level', 'list_marker', 'quote_level', 
        'table_headers', 'table_rows', 'table_align', 'table_col_widths', 
        'layout_lines', 'height', 'y_pos', 'x_offset', 
        'highlight_cache', 'language',
        # --- NEW FIELDS FOR COPY BUTTON ---
        'copy_rect',       # QRect of the button (relative to message)
        'is_copy_hovered', # Boolean for hover state
        'show_copied_text', # Boolean to show "Copied!" instead of "Copy"
        'table_row_heights' # List of heights for each row in the table
    )

    def __init__(self, text, block_type=BlockType.PARAGRAPH, level=1):
        self.text = text
        self.type = block_type
        self.level = level
        self.formatting: List[FormatRange] = [] 
        
        # List properties
        self.indent_level = 0
        self.list_marker = None  
        
        # Quote properties
        self.quote_level = 0
        
        # Table properties
        self.table_headers = [] 
        self.table_rows = []    
        self.table_align = []   
        self.table_col_widths = []
        self.table_row_heights = []

        # Layout cache
        self.layout_lines = [] 
        self.height = 0
        self.y_pos = 0 
        self.x_offset = 0
        
        self.highlight_cache = None
        self.language = None
        
        # --- INITIALIZE NEW FIELDS ---
        self.copy_rect = None
        self.is_copy_hovered = False
        self.show_copied_text = False

class Message:
    def __init__(self, text, is_user=False):
        self.is_user = is_user
        self.raw_text = text
        self.blocks = []
        self.total_height = 0
        self.y_pos = 0
        self.x_pos = 0
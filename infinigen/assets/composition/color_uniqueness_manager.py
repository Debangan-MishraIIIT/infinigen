# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Assistant

import numpy as np
from typing import Set, Dict, List, Optional
from infinigen.core.util.math import FixedSeed


class ColorUniquenessManager:
    """Manages color uniqueness across asset types to prevent duplicate colors."""
    
    _instance = None
    _used_colors: Set[str] = set()
    _color_alternatives: Dict[str, List[str]] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ColorUniquenessManager, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the color tracking for a new scene."""
        cls._used_colors = set()
        cls._color_alternatives = {}
    
    @classmethod
    def get_unique_color(cls, original_color: str, asset_type: str, factory_seed: int) -> str:
        """Get a unique color for an asset, changing it if necessary to avoid conflicts."""
        if original_color not in cls._used_colors:
            cls._used_colors.add(original_color)
            return original_color
        
        # Color is already used, find an alternative
        alternatives = cls._get_color_alternatives(original_color, asset_type, factory_seed)
        
        for alt_color in alternatives:
            if alt_color not in cls._used_colors:
                cls._used_colors.add(alt_color)
                print(f"Color conflict resolved: {asset_type} changed from '{original_color}' to '{alt_color}'")
                return alt_color
        
        # If all alternatives are used, use the original with a warning
        print(f"Warning: All color alternatives for '{original_color}' are already used for {asset_type}")
        return original_color
    
    @classmethod
    def _get_color_alternatives(cls, original_color: str, asset_type: str, factory_seed: int) -> List[str]:
        """Get alternative colors for a given original color."""
        if original_color in cls._color_alternatives:
            return cls._color_alternatives[original_color]
        
        # Define color alternatives based on the original color
        color_groups = {
            "white": ["black_wood", "wood", "blue", "green", "red", "yellow"],
            "black_wood": ["white", "wood", "blue", "green", "red", "yellow"],
            "wood": ["white", "black_wood", "blue", "green", "red", "yellow"],
            "blue": ["white", "black_wood", "wood", "green", "red", "yellow"],
            "green": ["white", "black_wood", "wood", "blue", "red", "yellow"],
            "red": ["white", "black_wood", "wood", "blue", "green", "yellow"],
            "yellow": ["white", "black_wood", "wood", "blue", "green", "red"],
        }
        
        alternatives = color_groups.get(original_color, ["white", "black_wood", "wood", "blue", "green", "red", "yellow"])
        
        # Shuffle alternatives using factory_seed for deterministic but varied results
        with FixedSeed(factory_seed):
            alternatives = np.random.permutation(alternatives).tolist()
        
        cls._color_alternatives[original_color] = alternatives
        return alternatives
    
    @classmethod
    def get_used_colors(cls) -> Set[str]:
        """Get the set of currently used colors."""
        return cls._used_colors.copy()
    
    @classmethod
    def is_color_used(cls, color: str) -> bool:
        """Check if a color is already used."""
        return color in cls._used_colors


def init_color_uniqueness_manager():
    """Initialize the color uniqueness manager for a new scene."""
    ColorUniquenessManager.reset()


def get_unique_color(original_color: str, asset_type: str, factory_seed: int) -> str:
    """Get a unique color for an asset, changing it if necessary to avoid conflicts."""
    return ColorUniquenessManager.get_unique_color(original_color, asset_type, factory_seed)

# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Assistant

import json
import os
from pathlib import Path
from typing import Dict, Any
import bpy


class MaterialLogger:
    """Global material logger for tracking material choices during asset creation."""
    
    _instance = None
    _output_folder = None
    _materials_log = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MaterialLogger, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def set_output_folder(cls, output_folder: Path):
        """Set the output folder for material logs."""
        cls._output_folder = output_folder
        cls._materials_log = {}
    
    @classmethod
    def log_material_choice(cls, factory_seed: int, factory_name: str, material_type: str, material_value: str):
        """Log a material choice for a specific factory."""
        if cls._output_folder is None:
            # Try to get output folder from Blender context
            if bpy.data.filepath:
                cls._output_folder = Path(bpy.data.filepath).parent
            else:
                # Fallback to current working directory
                cls._output_folder = Path.cwd()
        
        # Initialize factory list if it doesn't exist
        if factory_name not in cls._materials_log:
            cls._materials_log[factory_name] = []
        
        # Find existing entry for this factory_seed, or create new one
        factory_entry = None
        for entry in cls._materials_log[factory_name]:
            if entry["factory_seed"] == factory_seed:
                factory_entry = entry
                break
        
        if factory_entry is None:
            # Create new entry for this factory_seed
            factory_entry = {
                "factory_seed": factory_seed,
                "material": {}
            }
            cls._materials_log[factory_name].append(factory_entry)
        
        # Add the material choice to this factory instance
        factory_entry["material"][material_type] = material_value
        
        # Write to JSON file immediately
        cls._write_to_file()
    
    @classmethod
    def _write_to_file(cls):
        """Write the materials log to a single JSON file."""
        if cls._output_folder is None:
            return
        
        # Create materials directory if it doesn't exist
        materials_dir = cls._output_folder / "materials"
        materials_dir.mkdir(exist_ok=True)
        
        # Write all materials to a single file
        json_file = materials_dir / "materials.json"
        with open(json_file, 'w') as f:
            json.dump(cls._materials_log, f, indent=2)
    
    @classmethod
    def get_materials_log(cls) -> Dict[str, Dict[str, Any]]:
        """Get the current materials log."""
        return cls._materials_log.copy()


def init_material_logger(output_folder: Path):
    """Initialize the material logger with an output folder."""
    MaterialLogger.set_output_folder(output_folder)


def log_material_choice(factory_seed: int, factory_name: str, material_type: str, material_value: str):
    """Convenience function to log a material choice."""
    MaterialLogger.log_material_choice(factory_seed, factory_name, material_type, material_value)

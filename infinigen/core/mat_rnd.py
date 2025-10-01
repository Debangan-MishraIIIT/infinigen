import bpy
import random
from infinigen.assets.materials.wood.plywood import (
    shader_shelves_white,
    shader_shelves_yellow,
    shader_shelves_red,
    shader_shelves_blue,
    shader_shelves_green,
    shader_shelves_black_wood,
    shader_shelves_wood,
    get_shelf_material
)
import numpy as np


def apply_custom_stages(blend_file):
    from pathlib import Path
    blend_file = Path(blend_file)

    print(f"Loading blend file: {blend_file}")
    bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    print("Blend file loaded successfully")

    # Run material change fix
    material_change_fix()
    print("Material change fix completed")

    # Save the blend file with different name
    save_path = blend_file.parent / f"{blend_file.stem}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    print(f"Saved blend file to: {save_path}")


def delete_other_rooms():
    """
    Delete all objects in other rooms.
    """
    room_name = "bedroom"
    print("Deleting other rooms...")
    for obj in bpy.data.objects:
        if obj.name.startswith("Room"):
            bpy.data.objects.remove(obj)
    print("Other rooms deleted")


def material_change_fix():
    """
    Collect all objects in furniture categories and assign them different material colors.
    """
    # Convert blend_file to Path object if it's a string
    # from pathlib import Path
    # blend_file = Path(blend_file)
    
    # # Load the blend file first
    # print(f"Loading blend file: {blend_file}")
    # bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    # print("Blend file loaded successfully")
    
    # Define the categories to target
    target_categories = [
        "singlecabinet",
        "largeshelf", 
        "cellshelf",
        "simplebookcase",
        "cabinet",
        "kitchencabinet",
        "tvstand"
    ]
    
    # Define available shader functions
    shader_functions = [
        shader_shelves_white,
        shader_shelves_yellow,
        shader_shelves_red,
        shader_shelves_blue,
        shader_shelves_green,
        shader_shelves_black_wood,
        shader_shelves_wood
    ]
    
    # Collect all objects in target categories
    target_objects = []
    
    # Also search all objects as fallback
    print("Searching all objects as fallback...")
    for obj in bpy.data.objects:
        for category in target_categories:
            if category in obj.name.lower() and "spawn_asset" in obj.name.lower():
                target_objects.append(obj)
                print(f"MATCHED: {obj.name} contains {category}")
                break
    
    print(f"Found {len(target_objects)} objects in target categories")
    
    # Define color mappings for each shader function
    shader_colors = {
        shader_shelves_white: [0.9, 0.9, 0.9],
        shader_shelves_yellow: [0.95, 0.85, 0.4],
        shader_shelves_red: [0.40, 0.15, 0.18],
        shader_shelves_blue: [0.13, 0.23, 0.37],
        shader_shelves_green: [0.38, 0.47, 0.24],
        shader_shelves_black_wood: [0.02, 0.002, 0.002],
        shader_shelves_wood: [0.4, 0.3, 0.2]  # Brown wood color
    }
    # Randomize the order of target objects
    np.random.shuffle(target_objects)
    
    # Assign different colors to each object (cycling through shaders)
    for i, obj in enumerate(target_objects):
        # Cycle through shader functions to ensure each object gets a different shader
        selected_shader = shader_functions[i % len(shader_functions)]
        new_color = shader_colors[selected_shader]
        
        print(f"Processing object: {obj.name}")
        
        # Iterate through all materials of the object
        for material_slot in obj.material_slots:
            if material_slot.material:
                material = material_slot.material
                print(f"  Checking material: {material.name}")
                
                # Check if material name starts with "shader_shelves"
                if material.name.startswith("shader_shelves") or material.name.startswith("shader_rough_plastic"):
                    print(f"    -> Found shader_shelves material: {material.name}")
                    
                    # Ensure material uses nodes
                    material.use_nodes = True
                    
                    # Delete ColorRamp nodes
                    color_ramp_nodes = []
                    for node in material.node_tree.nodes:
                        if node.type == 'VALTORGB':  # ColorRamp node type
                            color_ramp_nodes.append(node)
                    
                    for color_ramp_node in color_ramp_nodes:
                        print(f"    -> Deleting ColorRamp node: {color_ramp_node.name}")
                        material.node_tree.nodes.remove(color_ramp_node)
                    
                    # Find the Principled BSDF node
                    principled_bsdf = None
                    for node in material.node_tree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            principled_bsdf = node
                            break
                    
                    # If no Principled BSDF found, create one
                    if principled_bsdf is None:
                        principled_bsdf = material.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
                        # Connect to material output
                        material_output = material.node_tree.nodes.get('Material Output')
                        if material_output:
                            material.node_tree.links.new(principled_bsdf.outputs['BSDF'], material_output.inputs['Surface'])
                    
                    # Change the Base Color of the Principled BSDF
                    old_color = principled_bsdf.inputs['Base Color'].default_value[:3]
                    principled_bsdf.inputs['Base Color'].default_value = (*new_color, 1.0)
                    
                    print(f"    -> Changed color from {old_color} to {new_color} using {selected_shader.__name__}")
                else:
                    print(f"    -> Skipping material: {material.name} (not shader_shelves or shader_rough_plastic)")
        
        print(f"Completed processing {obj.name}")
    
    print(f"Material assignment completed for {len(target_objects)} objects")

    # # Save the blend file with different name
    # save_path = blend_file.parent / f"{blend_file.stem}.blend"
    # bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    # print(f"Saved blend file to: {save_path}")
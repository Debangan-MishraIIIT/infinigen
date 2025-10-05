import os
import json
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

    # Run window orientation fix
    fix_window_orientation()
    print("Window orientation fix completed")

    # Run door orientation fix
    fix_door_orientation()
    print("Door orientation fix completed")

    # Save the blend file with different name
    save_path = blend_file.parent / f"{blend_file.stem}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    print(f"Saved blend file to: {save_path}")


def asset_info_json(blend_file):
    from pathlib import Path
    blend_file = Path(blend_file)

    print(f"Loading blend file: {blend_file}")
    bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    print("Blend file loaded successfully")

    for obj in bpy.data.objects:
        if "spawn_asset" in obj.name:
            print(f"Processing object: {obj.name}")
            print(f"Object type: {obj.type}")
            print(obj)


def fix_window_orientation():
    """
    Iterate through WindowFactory assets, check if their local Y axis is pointing inwards or outwards relative to the room.
    If pointing outwards, rotate by π around Z axis to make Y axis point inwards.
    """
    import bpy
    import numpy as np
    from mathutils import Vector, Matrix
    from infinigen_examples.constraints import home as home_constraints

    consgraph_rooms = home_constraints.home_room_constraints()
    constants = consgraph_rooms.constants
    print(f"Wall thickness half: {constants.wall_thickness / 2}")

    #########################################################
    # from pathlib import Path
    # blend_file = Path(blend_file)

    # print(f"Loading blend file: {blend_file}")
    # bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    # print("Blend file loaded successfully")
    #########################################################

    # Find all WindowFactory objects
    window_objects = []
    for obj in bpy.data.objects:
        if "WindowFactory" in obj.name:
            if not obj.hide_render:
                window_objects.append(obj)

    print(f"Found {len(window_objects)} window objects")

    # Find the single room object
    room = None
    for obj in bpy.data.objects:
        if ("living" in obj.name.lower() or
            "bedroom" in obj.name.lower() or "kitchen" in obj.name.lower() or
            "dining" in obj.name.lower() or "bathroom" in obj.name.lower()):
            # Check if this looks like a room object (has /0.exterior pattern)
            if "/0.exterior" in obj.name or "/0.interior" in obj.name:
                # Only process rooms that are NOT hidden from render (visible rooms)
                if not obj.hide_render:
                    room = obj
                    break

    if not room:
        print("Could not find room object")
        return

    print(f"Found room: {room.name}")

    for window_obj in window_objects:
        print(f"Processing window: {window_obj.name}")
        print(f"Window {window_obj.name} belongs to room {room.name}")

        # Get window's current transformation matrix
        window_matrix = window_obj.matrix_world

        # Get window's local Y axis in world space (this is the direction we want to check)
        # We need to use only the rotation part, not the translation
        window_y_axis = Vector((0, 1, 0))  # Local Y direction
        # Extract rotation matrix (3x3 upper-left part) and transform the Y axis
        rotation_matrix = window_matrix.to_3x3()
        window_y_axis_world = rotation_matrix @ window_y_axis
        window_y_axis_world.normalize()
        
        print(f"Window Y axis (world): {window_y_axis_world}")

        # Get room center
        room_center = room.location
        print(f"Room center: {room_center}")
        print(f"Window world location: {window_obj.matrix_world.translation}")
        
        # Vector from window to room center
        window_to_room = room_center - window_obj.matrix_world.translation
        window_to_room.normalize()
        print(f"Window to room direction: {window_to_room}")

        # Check if window Y axis is pointing inward or outward
        # We'll use 3D dot product for more accurate results
        dot_product = window_y_axis_world.dot(window_to_room)

        print(f"Window Y axis: {window_y_axis_world}")
        print(f"Direction to room center: {window_to_room}")
        print(f"Dot product: {dot_product}")

        if dot_product > 0:
            # Y axis is pointing outward, need to rotate 180° around Z
            print(f"Rotating window {window_obj.name} 180° around Z axis")

            # Create rotation matrix for 180° around Z
            rotation_matrix = Matrix.Rotation(np.pi, 4, 'Z')

            # Apply rotation to window
            window_obj.matrix_world = window_obj.matrix_world @ rotation_matrix
            
            # Verify the rotation worked
            new_rotation_matrix = window_obj.matrix_world.to_3x3()
            new_y_axis = new_rotation_matrix @ Vector((0, 1, 0))
            new_y_axis.normalize()
            new_dot_product = new_y_axis.dot(window_to_room)
            print(f"After rotation - Y axis: {new_y_axis}, new dot product: {new_dot_product}")
        else:
            print(f"Window {window_obj.name} Y axis is already pointing inward")

        # Determine wall positioning by trying both offsets and choosing the one closer to room center
        window_pos = window_obj.matrix_world.translation
        room_center = room.location
        
        # Try positive offset
        pos_offset = constants.wall_thickness / 2
        # Create world position with positive offset applied
        pos_world_matrix = window_obj.matrix_world
        print(f"Initial Positive world matrix: {pos_world_matrix.translation}")
        print(f"Initial Positive location: {window_obj.location}")
        window_obj.location[1] = pos_offset
        print(f"Positive location: {window_obj.location}")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        pos_world_matrix = window_obj.matrix_world
        print(f"Positive world matrix: {pos_world_matrix.translation}")
        print(f"Room center: {room_center}")
        pos_distance = (pos_world_matrix.translation - room_center).length

        # Try negative offset
        neg_offset = -constants.wall_thickness / 2
        # Create world position with negative offset applied
        neg_world_matrix = window_obj.matrix_world
        print(f"Negative world matrix: {neg_world_matrix.translation}")
        print(f"Initial Negative location: {window_obj.location}")
        window_obj.location[1] = neg_offset
        print(f"Negative location: {window_obj.location}")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        neg_world_matrix = window_obj.matrix_world
        print(f"Negative world matrix: {neg_world_matrix.translation}")
        print(f"Room center: {room_center}")
        neg_distance = (neg_world_matrix.translation - room_center).length
        
        # Choose the offset that results in the window being closer to room center
        if pos_distance < neg_distance:
            wall_offset = pos_offset
            print(f"Window {window_obj.name} - Positive offset closer (dist: {pos_distance:.2f} vs {neg_distance:.2f}), using +{wall_offset}")
        else:
            wall_offset = neg_offset
            print(f"Window {window_obj.name} - Negative offset closer (dist: {neg_distance:.2f} vs {pos_distance:.2f}), using {wall_offset}")
        
        window_obj.location[1] = wall_offset
    #########################################################
    # Save the blend file with different name
    # save_path = blend_file.parent / f"{blend_file.stem}_fixed.blend"
    # bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    # print(f"Saved blend file to: {save_path}")
    #########################################################


def fix_door_orientation():
    """
    Iterate through WindowFactory assets, check if their local Y axis is pointing inwards or outwards relative to the room.
    If pointing outwards, rotate by π around Z axis to make Y axis point inwards.
    """
    import bpy
    import numpy as np
    from mathutils import Vector, Matrix
    # from infinigen_examples.constraints import home as home_constraints

    # consgraph_rooms = home_constraints.home_room_constraints()
    # constants = consgraph_rooms.constants
    # print(f"Wall thickness half: {constants.wall_thickness / 2}")

    #########################################################
    # from pathlib import Path
    # blend_file = Path(blend_file)

    # print(f"Loading blend file: {blend_file}")
    # bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    # print("Blend file loaded successfully")
    #########################################################

    # Find all WindowFactory objects
    door_objects = []
    for obj in bpy.data.objects:
        if "DoorFactory" in obj.name:
            if not obj.hide_render:
                door_objects.append(obj)

    print(f"Found {len(door_objects)} door objects")

    # Find the single room object
    room = None
    for obj in bpy.data.objects:
        if ("living" in obj.name.lower() or
            "bedroom" in obj.name.lower() or "kitchen" in obj.name.lower() or
            "dining" in obj.name.lower() or "bathroom" in obj.name.lower()):
            # Check if this looks like a room object (has /0.exterior pattern)
            if "/0.exterior" in obj.name or "/0.interior" in obj.name:
                # Only process rooms that are NOT hidden from render (visible rooms)
                if not obj.hide_render:
                    room = obj
                    break

    if not room:
        print("Could not find room object")
        return

    print(f"Found room: {room.name}")

    for door_obj in door_objects:
        print(f"Processing window: {door_obj.name}")
        print(f"Window {door_obj.name} belongs to room {room.name}")

        # Get window's current transformation matrix
        door_matrix = door_obj.matrix_world

        # Get window's local Y axis in world space (this is the direction we want to check)
        # We need to use only the rotation part, not the translation
        door_y_axis = Vector((0, 1, 0))  # Local Y direction
        # Extract rotation matrix (3x3 upper-left part) and transform the Y axis
        rotation_matrix = door_matrix.to_3x3()
        door_y_axis_world = rotation_matrix @ door_y_axis
        door_y_axis_world.normalize()
        
        print(f"Door Y axis (world): {door_y_axis_world}")

        # Get room center
        room_center = room.location
        print(f"Room center: {room_center}")
        print(f"Door world location: {door_obj.matrix_world.translation}")
            
        # Vector from window to room center
        door_to_room = room_center - door_obj.matrix_world.translation
        door_to_room.normalize()
        print(f"Door to room direction: {door_to_room}")

        # Check if window Y axis is pointing inward or outward
        # We'll use 3D dot product for more accurate results
        dot_product = door_y_axis_world.dot(door_to_room)

        print(f"Door Y axis: {door_y_axis_world}")
        print(f"Direction to room center: {door_to_room}")
        print(f"Dot product: {dot_product}")

        if dot_product < 0:
            # Y axis is pointing outward, need to mirror around local Y axis
            # print(f"Mirroring door {door_obj.name} around local Y axis")

            # # Get current transformation matrices
            # world_matrix = door_obj.matrix_world.copy()
            # local_matrix = door_obj.matrix_local.copy()

            # # Create mirror transformation that flips the door's orientation
            # # This mirrors around the plane that would change the facing direction
            # mirror_transform = Matrix([
            #     [1, 0, 0, 0],
            #     [0, -1, 0, 0],
            #     [0, 0, 1, 0],
            #     [0, 0, 0, 1]
            # ])

            # # Apply mirror in local coordinate system
            # # Transform to local, apply mirror, transform back to world
            # door_obj.matrix_world = (world_matrix @
            #                        local_matrix.inverted() @
            #                        mirror_transform @
            #                        local_matrix)

            # door_obj.select_set(True)
            # bpy.ops.transform.mirror(
            #     orient_type='LOCAL',
            #     orient_matrix_type='LOCAL',
            #     constraint_axis=(False, True, False)
            # )

            # depsgraph = bpy.context.evaluated_depsgraph_get()
            # depsgraph.update()
            # door_obj.select_set(False)

            mirror_local_y(door_obj)


            # Verify the mirroring worked
            new_rotation_matrix = door_obj.matrix_world.to_3x3()
            new_y_axis = new_rotation_matrix @ Vector((0, 1, 0))
            new_y_axis.normalize()
            new_dot_product = new_y_axis.dot(door_to_room)
            print(f"After mirroring - Y axis: {new_y_axis}, new dot product: {new_dot_product}")
        else:
            print(f"Door {door_obj.name} Y axis is already pointing inward")

        # door_obj.location[1] = - constants.wall_thickness / 2
    #########################################################
    # Save the blend file with different name
    # save_path = blend_file.parent / f"{blend_file.stem}_fixed.blend"
    # bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    # print(f"Saved blend file to: {save_path}")
    #########################################################


def mirror_local_y(obj):
    # Always in Object Mode
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Select only this object and make it active
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Force pivot/orientation so it mirrors in place about the object's origin
    bpy.context.tool_settings.transform_pivot_point = 'INDIVIDUAL_ORIGINS'
    bpy.ops.transform.mirror(
        orient_type='LOCAL',
        orient_matrix_type='LOCAL',
        constraint_axis=(False, True, False)
    )
    bpy.context.view_layer.update()


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
    
    print("target_objects: ", target_objects)
    print("target_objects names: ", [obj.name for obj in target_objects])
    print(f"Found {len(target_objects)} objects in target categories")

    ############################################################
    # in asset_parameters.json, remove the objects that are not in bpy.data.objects
    # go over dicts which belong to target categories and remove the ones that are not in target_objects
    scene_folder = os.environ.get('INFINIGEN_OUTPUT_DIR')
    if os.path.exists(os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")):
        asset_dict = json.load(open(os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")))
    else:
        asset_dict = {}
    to_remove = []
    print("asset_dict.keys(): ", asset_dict.keys())
    print("target_objects: ", [obj.name for obj in target_objects])
    for category in target_categories:
        for dict_key in asset_dict.keys():
            if category in dict_key.lower() and dict_key not in [obj.name for obj in target_objects]:
                to_remove.append(dict_key)
    print("to_remove: ", to_remove)
    to_remove = list(set(to_remove))
    for dict_key in to_remove:
        del asset_dict[dict_key]
    json_path = os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")
    with open(json_path, "w") as f:
        json.dump(asset_dict, f, default=str, indent=2)
    ############################################################

    
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
    color_name_mapping = {
        shader_shelves_white: "white",
        shader_shelves_yellow: "yellow",
        shader_shelves_red: "red",
        shader_shelves_blue: "blue",
        shader_shelves_green: "green",
        shader_shelves_black_wood: "black_wood",
        shader_shelves_wood: "wood"
    }
    # Randomize the order of target objects
    np.random.shuffle(target_objects)
    
    # Assign different colors to each object (randomly sampling shaders)
    for i, obj in enumerate(target_objects):
        # Randomly sample a shader function
        selected_shader = np.random.choice(shader_functions)
        new_color = shader_colors[selected_shader]
        color_name = color_name_mapping[selected_shader]
        
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
        ############################################################
        # for the target object, update the corresponding dictionary in the asset_parameters.json file
        # scene_folder = os.environ.get('INFINIGEN_OUTPUT_DIR')
        # json_path = os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")
        # with open(json_path, "r") as f:
        #     asset_dict = json.load(f)
        # asset_dict[f"{repr(obj)}.spawn_asset({i})"]["color"] = new_color
        # with open(json_path, "w") as f:
        #     json.dump(asset_dict, f, default=str, indent=2)
        scene_folder = os.environ.get('INFINIGEN_OUTPUT_DIR')
        if os.path.exists(os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")):
            asset_dict = json.load(open(os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")))
        else:
            asset_dict = {}
        print("asset_dict.keys(): ", asset_dict.keys())
        print("obj.name: ", obj.name)
        if obj.name in asset_dict.keys():
            asset_dict[obj.name]["color"] = color_name
        else:
            asset_dict[obj.name] = {"color": color_name}
        json_path = os.path.join(scene_folder if scene_folder else ".", "asset_parameters.json")
        with open(json_path, "w") as f:
            json.dump(asset_dict, f, default=str, indent=2)
        ############################################################
    
    print(f"Material assignment completed for {len(target_objects)} objects")

    # # Save the blend file with different name
    # save_path = blend_file.parent / f"{blend_file.stem}.blend"
    # bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    # print(f"Saved blend file to: {save_path}")
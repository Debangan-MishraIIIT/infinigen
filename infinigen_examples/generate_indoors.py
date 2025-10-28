# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

import argparse
import logging
from pathlib import Path
import os
from mathutils import Vector, Matrix

# ruff: noqa: E402
# NOTE: logging config has to be before imports that use logging
logging.basicConfig(
    format="[%(asctime)s.%(msecs)03d] [%(module)s] [%(levelname)s] | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

import bpy
import gin
import numpy as np

from infinigen import repo_root
from infinigen.assets import lighting
from infinigen.assets.materials.dev import InvisibleToCamera
from infinigen.assets.objects.wall_decorations.skirting_board import make_skirting_board
from infinigen.assets.placement.floating_objects import FloatingObjectPlacement
from infinigen.assets.utils.decorate import read_co
from infinigen.core import execute_tasks, init, placement, tagging
from infinigen.core import tags as t
from infinigen.core.constraints import checks
from infinigen.core.constraints import constraint_language as cl
from infinigen.core.constraints import reasoning as r
from infinigen.core.constraints.example_solver import (
    greedy,
    populate,
    state_def,
)
from mathutils.bvhtree import BVHTree

from infinigen.core.constraints.example_solver.room import decorate as room_dec
from infinigen.core.constraints.example_solver.solve import Solver
from infinigen.core.placement import camera_trajectories as cam_traj
from infinigen.core.util import blender as butil
from infinigen.core.util import camera as cam_util
from infinigen.core.util import ocmesher_utils, pipeline
from infinigen.core.util.imu import save_imu_tum_files
from infinigen.core.util.test_utils import (
    import_item,
    load_txt_list,
)
from infinigen.terrain import Terrain
from infinigen.tools.convert_displacement import convert_shader_displacement
from infinigen_examples.constraints import home as home_constraints
from infinigen_examples.constraints import util as cu
from infinigen_examples.util.generate_indoors_util import (
    apply_greedy_restriction,
    create_outdoor_backdrop,
    hide_other_rooms,
    place_cam_overhead,
    restrict_solving,
)

from . import (
    generate_nature,  # noqa: F401 # needed for nature gin configs to be loaded
)

logger = logging.getLogger(__name__)


def default_greedy_stages():
    """Returns descriptions of what will be covered by each greedy stage of the solver.

    Any domain containing one or more VariableTags is greedy: it produces many separate domains,
        one for each possible assignment of the unresolved variables.
    """

    on_floor = cl.StableAgainst({}, cu.floortags)
    on_wall = cl.StableAgainst({}, cu.walltags)
    on_ceiling = cl.StableAgainst({}, cu.ceilingtags)
    side = cl.StableAgainst({}, cu.side)

    all_room = r.Domain({t.Semantics.Room, -t.Semantics.Object})
    all_obj = r.Domain({t.Semantics.Object, -t.Semantics.Room})

    all_obj_in_room = all_obj.with_relation(
        cl.AnyRelation(), all_room.with_tags(cu.variable_room)
    )
    primary = all_obj_in_room.with_relation(-cl.AnyRelation(), all_obj)

    greedy_stages = {}

    greedy_stages["rooms"] = all_room

    greedy_stages["on_floor_and_wall"] = primary.with_relation(
        on_floor, all_room
    ).with_relation(on_wall, all_room)
    greedy_stages["on_floor_freestanding"] = primary.with_relation(
        on_floor, all_room
    ).with_relation(-on_wall, all_room)
    greedy_stages["on_wall"] = (
        primary.with_relation(-on_floor, all_room)
        .with_relation(-on_ceiling, all_room)
        .with_relation(on_wall, all_room)
    )
    greedy_stages["on_ceiling"] = (
        primary.with_relation(-on_floor, all_room)
        .with_relation(on_ceiling, all_room)
        .with_relation(-on_wall, all_room)
    )

    secondary = all_obj.with_relation(
        cl.AnyRelation(), all_obj_in_room.with_tags(cu.variable_obj)
    )

    greedy_stages["side_obj"] = (
        secondary.with_relation(side, all_obj)
        .with_relation(-cu.on, all_obj)
        .with_relation(-cu.ontop, all_obj)
    )

    greedy_stages["obj_ontop_obj"] = (
        secondary.with_relation(-side, all_obj)
        .with_relation(cu.ontop, all_obj)
        .with_relation(-cu.on, all_obj)
    )
    greedy_stages["obj_on_support"] = (
        secondary.with_relation(-side, all_obj)
        .with_relation(cu.on, all_obj)
        .with_relation(-cu.ontop, all_obj)
    )

    return greedy_stages


all_vars = [cu.variable_room, cu.variable_obj]


@gin.configurable
def compose_indoors(output_folder: Path, scene_seed: int, **overrides):
    #########################################################
    os.environ['INFINIGEN_OUTPUT_DIR'] = str(output_folder)
    #########################################################

    p = pipeline.RandomStageExecutor(scene_seed, output_folder, overrides)

    logger.debug(overrides)

    def add_coarse_terrain():
        terrain = Terrain(
            scene_seed,
            task="coarse",
            on_the_fly_asset_folder=output_folder / "assets",
        )
        terrain_mesh = terrain.coarse_terrain()
        # placement.density.set_tag_dict(terrain.tag_dict)
        return terrain, terrain_mesh

    terrain, terrain_mesh = p.run_stage(
        "terrain", add_coarse_terrain, use_chance=False, default=(None, None)
    )

    p.run_stage("sky_lighting", lighting.sky_lighting.add_lighting, use_chance=False)

    consgraph = home_constraints.home_furniture_constraints()
    consgraph_rooms = home_constraints.home_room_constraints()
    constants = consgraph_rooms.constants

    stages = default_greedy_stages()
    checks.check_all(consgraph, stages, all_vars)
    
    stages, consgraph, limits, restrict_parent_rooms = restrict_solving(stages, consgraph)


    if overrides.get("restrict_single_supported_roomtype", False):
        restrict_parent_rooms = {
            np.random.choice(
                [
                    # Only these roomtypes have constraints written in home_furniture_constraints.
                    # Others will be empty-ish besides maybe storage and plants
                    # TODO: add constraints to home_furniture_constraints for garages, offices, balconies, etc
                    t.Semantics.Bedroom,
                    t.Semantics.LivingRoom,
                    t.Semantics.Kitchen,
                    t.Semantics.Bathroom,
                    t.Semantics.DiningRoom,
                ]
            )
        }
        logger.info(f"Restricting to {restrict_parent_rooms}")
        apply_greedy_restriction(stages, restrict_parent_rooms, cu.variable_room)

    solver = Solver(output_folder=output_folder)

    def solve_rooms():
        return solver.solve_rooms(scene_seed, consgraph_rooms, stages["rooms"])

    state: state_def.State = p.run_stage("solve_rooms", solve_rooms, use_chance=False)
    
    #########################################################
    state.to_json(output_folder / "rooms.json")
    # print("Line 193 - generate_indoors.py - state:", state)
    # Check if room in restrict_parent_rooms in state, the polygon should have 5 vertices
    restrict_parent_rooms_str = restrict_parent_rooms[0].lower()+"_0/0"
    if restrict_parent_rooms_str == "livingroom_0/0":
        restrict_parent_rooms_str = "living-room_0/0"
    if restrict_parent_rooms_str == "diningroom_0/0":
        restrict_parent_rooms_str = "dining-room_0/0"
    
    for room in state.objs.values():
        print("Line 205 - generate_indoors.py - room:", room)
        print("Line 206 - generate_indoors.py - restrict_parent_rooms:", restrict_parent_rooms)
        print("Line 207 - generate_indoors.py - room.obj.name:", room.obj.name)
        print("Line 208 - generate_indoors.py - restrict_parent_rooms_str:", restrict_parent_rooms_str)
        if room.obj.name == restrict_parent_rooms_str:
            print("Rectangluar Room Found!")
            print("Line 210 - generate_indoors.py - room.polygon:", room.polygon)
            assert len(room.polygon.exterior.coords) == 5, f"Room {room.obj.name} in restrict_parent_rooms should have 5 vertices"

    
    if restrict_parent_rooms_str == "bathroom_0/0":
        for room in state.objs.values():
            if room.obj.name == "bathroom_0/0":
                door_count = 0
                for relation in room.relations:
                    # print("Line 220 - generate_indoors.py - relation.relation:", relation.relation)
                    # print("Line 221 - generate_indoors.py - relation.relation.connector_types:", relation.relation.connector_types)
                    # print("Line 222 - generate_indoors.py - relation.relation.connector_types values:", relation.relation.connector_types)
                    if any(connector.value == 'door' for connector in relation.relation.connector_types):
                        # print("Line 224 - generate_indoors.py - door found")
                        door_count += 1
                assert door_count == 1, f"Bathroom {room.obj.name} should have 1 door"
                # print("Line 226 - generate_indoors.py - bathroom door_count:", door_count)

    #########################################################


    def solve_stage_name(stage_name: str, group: str, **kwargs):
        assigments = greedy.iterate_assignments(
            stages[stage_name], state, all_vars, limits
        )
        for i, vars in enumerate(assigments):
            solver.solve_objects(
                consgraph,
                stages[stage_name],
                vars,
                n_steps=overrides[f"solve_steps_{group}"],
                desc=f"{stage_name}_{i}",
                abort_unsatisfied=overrides.get(f"abort_unsatisfied_{group}", False),
                **kwargs,
            )

    def solve_large():
        solve_stage_name("on_floor_and_wall", "large")
        solve_stage_name("on_floor_freestanding", "large") 

    p.run_stage("solve_large", solve_large, use_chance=False, default=state)

    solved_rooms = [
        state.objs[assignment[cu.variable_room]].obj
        for assignment in greedy.iterate_assignments(
            stages["on_floor_freestanding"], state, [cu.variable_room], limits
        )
    ]
    solved_bound_points = np.concatenate([butil.bounds(r) for r in solved_rooms])
    solved_bbox = (
        np.min(solved_bound_points, axis=0),
        np.max(solved_bound_points, axis=0),
    )

    house_bbox = np.concatenate(
        [
            butil.bounds(obj)
            for obj in solver.get_bpy_objects(r.Domain({t.Semantics.Room}))
        ]
    )
    house_bbox = (np.min(house_bbox, axis=0), np.max(house_bbox, axis=0))


    nonroom_objs = [
        o.obj for o in state.objs.values() if t.Semantics.Room not in o.tags
    ]
    room_objs = [o.obj for o in state.objs.values() if t.Semantics.Room in o.tags]
    scene_objs = solved_rooms + nonroom_objs



    #########################################################
    # # Create a dict with all objects in the scene and their bounding boxes
    print("State objects:", state.objs.values())
    
    def get_global_bbox(obj):
        """Get bounding box in global coordinates."""
        # Get local bounding box
        local_min, local_max = butil.bounds(obj)

        print("Object name:", obj.name)
        print("Local min:", local_min)
        print("Local max:", local_max)
        
        # Get the object's world transformation matrix and convert to numpy
        world_matrix = np.array(obj.matrix_world)
        
        # Transform the 8 corners of the local bounding box to global space
        corners = np.array([
            [local_min[0], local_min[1], local_min[2], 1],
            [local_max[0], local_min[1], local_min[2], 1],
            [local_min[0], local_max[1], local_min[2], 1],
            [local_max[0], local_max[1], local_min[2], 1],
            [local_min[0], local_min[1], local_max[2], 1],
            [local_max[0], local_min[1], local_max[2], 1],
            [local_min[0], local_max[1], local_max[2], 1],
            [local_max[0], local_max[1], local_max[2], 1],
        ])
        
        # Transform all corners to global space
        global_corners = (world_matrix @ corners.T).T[:, :3]  # Remove homogeneous coordinate
        
        # Find the axis-aligned bounding box of the transformed corners
        global_min = np.min(global_corners, axis=0)
        global_max = np.max(global_corners, axis=0)
        
        return global_min, global_max

    def get_global_bbox_new(obj):
        print("Line 326 - generate_indoors.py - obj.bound_box:", obj.bound_box)
        # print the numpy array of obj.bound_box
        # print obj name and obj bound box
        print("Line 327 - generate_indoors.py - obj name:", obj.name)
        print("Line 327 - generate_indoors.py - obj.bound_box numpy array:", np.array(obj.bound_box))
        print("Line 327 - generate_indoors.py - obj.matrix_world:", obj.matrix_world)
        # global_corners = [list(obj.matrix_world @ Vector(corner)) for corner in obj.bound_box]

        matrix_world = np.array(obj.matrix_world)
        obj_bound_box = np.array(obj.bound_box)


        ones = np.ones((obj_bound_box.shape[0], 1))
        coords_hom = np.hstack((obj_bound_box, ones))

        # apply transformation
        global_corners = (matrix_world @ coords_hom.T).T[:, :3]

        global_min = np.min(global_corners, axis=0)
        global_max = np.max(global_corners, axis=0)

        print("Line 345 - generate_indoors.py - global_min:", global_min)
        print("Line 346 - generate_indoors.py - global_max:", global_max)
        return global_min, global_max
    
    # Get bounding boxes in global coordinates
    scene_objs_bbox = {o.name: get_global_bbox_new(o) for o in scene_objs}
    print("Line 281 - generate_indoors.py - scene_objs_bbox (GLOBAL):", scene_objs_bbox)

    def check_bbox_overlap(bbox1, bbox2, overlap_threshold=0.1):
        """
        Check if two bounding boxes have significant overlap.
        
        Args:
            bbox1, bbox2: Tuples of (min_corner, max_corner) where each corner is (x, y, z)
            overlap_threshold: Minimum overlap ratio to consider as significant (0.0 to 1.0)
            
        Returns:
            tuple: (has_overlap, overlap_ratio, overlap_volume)
        """
        min1, max1 = bbox1
        min2, max2 = bbox2
        
        # Calculate intersection bounds
        intersect_min = np.maximum(min1, min2)
        intersect_max = np.minimum(max1, max2)
        
        # Check if there's any intersection
        if np.any(intersect_min >= intersect_max):
            return False, 0.0, 0.0
        
        # Calculate intersection volume
        intersect_dims = intersect_max - intersect_min
        intersect_volume = np.prod(intersect_dims)
        
        # Calculate volumes of both bounding boxes
        bbox1_dims = max1 - min1
        bbox1_volume = np.prod(bbox1_dims)
        
        bbox2_dims = max2 - min2
        bbox2_volume = np.prod(bbox2_dims)
        
        # Calculate overlap ratio (intersection volume / smaller bounding box volume)
        smaller_volume = min(bbox1_volume, bbox2_volume)
        overlap_ratio = intersect_volume / smaller_volume if smaller_volume > 0 else 0.0
        
        has_overlap = overlap_ratio >= overlap_threshold
        
        return has_overlap, overlap_ratio, intersect_volume

    def find_object_overlaps(scene_objs_bbox, overlap_threshold=0.1):
        """
        Find overlapping objects in the scene, excluding windows and doors.
        
        Args:
            scene_objs_bbox: Dictionary mapping object names to their bounding boxes
            overlap_threshold: Minimum overlap ratio to consider as significant
            
        Returns:
            list: List of tuples (obj1_name, obj2_name, overlap_ratio, overlap_volume)
        """
        overlaps = []
        object_names = list(scene_objs_bbox.keys())
        
        # Filter out windows and doors
        filtered_objects = []
        for name in object_names:
            if not (name.startswith('window') or name.startswith('door') or name == 'entrance'):
                filtered_objects.append(name)
        
        print(f"Checking overlaps among {len(filtered_objects)} objects (excluding windows/doors)")
        
        # Check all pairs of filtered objects
        for i in range(len(filtered_objects)):
            for j in range(i + 1, len(filtered_objects)):
                obj1_name = filtered_objects[i]
                obj2_name = filtered_objects[j]
                
                bbox1 = scene_objs_bbox[obj1_name]
                bbox2 = scene_objs_bbox[obj2_name]
                
                has_overlap, overlap_ratio, overlap_volume = check_bbox_overlap(
                    bbox1, bbox2, overlap_threshold
                )
                
                if has_overlap:
                    overlaps.append((obj1_name, obj2_name, overlap_ratio, overlap_volume))
                    print(f"OVERLAP FOUND: {obj1_name} <-> {obj2_name}")
                    print(f"  Overlap ratio: {overlap_ratio:.3f}")
                    print(f"  Overlap volume: {overlap_volume:.3f}")
                    print(f"  BBox1: {bbox1}")
                    print(f"  BBox2: {bbox2}")
                    print()
                else:
                    print("No overlap found between two objects")
                    print(f"  Object1: {obj1_name}")
                    print(f"  Object2: {obj2_name}")
                    print(f"  BBox1: {bbox1}")
                    print(f"  BBox2: {bbox2}")
                    print(f"  Overlap ratio: {overlap_ratio:.3f}")
                    print(f"  Overlap volume: {overlap_volume:.3f}")
        
        return overlaps

    # Check for overlaps
    overlaps = find_object_overlaps(scene_objs_bbox, overlap_threshold=0.1)
    
    if overlaps:
        print(f"Found {len(overlaps)} overlapping object pairs:")
        for obj1, obj2, ratio, volume in overlaps:
            print(f"  {obj1} <-> {obj2}: {ratio:.3f} ratio, {volume:.3f} volume")
            if "room" in obj1 or "room" in obj2:
                print("Room overlap must be 100%")
                print("If not, then assert fails and the script will crash")
                # assert ratio == 1, f"Room should have 100% overlap with all other objects"
            else:
                if 'rug' in obj1 or 'rug' in obj2:
                    print("Rug overlap is allowed")
                else:
                    print("There is an overlap between two objects that are not rooms or rugs")
                    # raise RuntimeError(f"Object {obj1} or {obj2} has an overlap ratio of {ratio}")
    else:
        print("No significant overlaps found between objects (excluding windows/doors)")

    #########################################################


    #########################################################
    # # FIXING WINDOW ORIENTATION
    # consgraph_rooms = home_constraints.home_room_constraints()
    # constants = consgraph_rooms.constants
    # # print(f"Wall thickness half: {constants.wall_thickness / 2}")

    # # Find all WindowFactory objects
    # window_objects = []
    # for obj in bpy.data.objects:
    #     print("Line 482 - generate_indoors.py - obj.name:", obj.name)
    #     if "window" in obj.name:
    #         if not obj.hide_render:
    #             window_objects.append(obj)

    # print(f"Found {len(window_objects)} window objects")

    # # Find the single room object
    # room = None
    # for obj in bpy.data.objects:
    #     print("restrict_parent_rooms_str:", restrict_parent_rooms_str)
    #     if (restrict_parent_rooms_str in obj.name.lower()):
    #         # Check if this looks like a room object (has /0.exterior pattern)
    #         # if "/0.exterior" in obj.name or "/0.interior" in obj.name:
    #             # Only process rooms that are NOT hidden from render (visible rooms)
    #         if not obj.hide_render:
    #             room = obj
    #             break

    # if not room:
    #     print("Could not find room object")
    #     return

    # print(f"Found room: {room.name}")

    # for window_obj in window_objects:
    #     print(f"Processing window: {window_obj.name}")
    #     print(f"Window {window_obj.name} belongs to room {room.name}")

    #     # Get window's current transformation matrix
    #     window_matrix = window_obj.matrix_world

    #     # Get window's local Y axis in world space (this is the direction we want to check)
    #     # We need to use only the rotation part, not the translation
    #     window_y_axis = Vector((0, 1, 0))  # Local Y direction
    #     # Extract rotation matrix (3x3 upper-left part) and transform the Y axis
    #     rotation_matrix = Matrix(window_matrix.to_3x3())
    #     window_y_axis_world = rotation_matrix @ window_y_axis
    #     window_y_axis_world.normalize()
        
    #     print(f"Window Y axis (world): {window_y_axis_world}")

    #     # Get room center
    #     room_center = room.location
    #     print(f"Room center: {room_center}")
    #     print(f"Window world location: {window_obj.matrix_world.translation}")
        
    #     # Vector from window to room center
    #     window_to_room = room_center - window_obj.matrix_world.translation
    #     window_to_room.normalize()
    #     print(f"Window to room direction: {window_to_room}")

    #     # Check if window Y axis is pointing inward or outward
    #     # We'll use 3D dot product for more accurate results
    #     dot_product = window_y_axis_world.dot(window_to_room)

    #     print(f"Window Y axis: {window_y_axis_world}")
    #     print(f"Direction to room center: {window_to_room}")
    #     print(f"Dot product: {dot_product}")

    #     if dot_product > 0:
    #         # Y axis is pointing outward, need to rotate 180° around Z
    #         print(f"Rotating window {window_obj.name} 180° around Z axis")

    #         # Create rotation matrix for 180° around Z
    #         rotation_matrix = Matrix.Rotation(np.pi, 4, 'Z')

    #         # Apply rotation to window
    #         window_obj.matrix_world = Matrix(window_obj.matrix_world) @ rotation_matrix
            
    #         # Verify the rotation worked
    #         new_rotation_matrix = Matrix(window_obj.matrix_world.to_3x3())
    #         new_y_axis = new_rotation_matrix @ Vector((0, 1, 0))
    #         new_y_axis.normalize()
    #         new_dot_product = new_y_axis.dot(window_to_room)
    #         print(f"After rotation - Y axis: {new_y_axis}, new dot product: {new_dot_product}")
    #     else:
    #         print(f"Window {window_obj.name} Y axis is already pointing inward")

    #     # Determine wall positioning by trying both offsets and choosing the one closer to room center
    #     window_pos = window_obj.matrix_world.translation
    #     room_center = room.location
        
    #     # Try positive offset
    #     pos_offset = constants.wall_thickness / 2
    #     # Create world position with positive offset applied
    #     pos_world_matrix = window_obj.matrix_world
    #     print(f"Initial Positive world matrix: {pos_world_matrix.translation}")
    #     print(f"Initial Positive location: {window_obj.location}")
    #     window_obj.location[1] += pos_offset
    #     print(f"Positive location: {window_obj.location}")
    #     depsgraph = bpy.context.evaluated_depsgraph_get()
    #     depsgraph.update()
    #     pos_world_matrix = window_obj.matrix_world
    #     print(f"Positive world matrix: {pos_world_matrix.translation}")
    #     print(f"Room center: {room_center}")
    #     pos_distance = (pos_world_matrix.translation - room_center).length

    #     # Try negative offset
    #     neg_offset = -constants.wall_thickness / 2
    #     # Create world position with negative offset applied
    #     neg_world_matrix = window_obj.matrix_world
    #     print(f"Negative world matrix: {neg_world_matrix.translation}")
    #     print(f"Initial Negative location: {window_obj.location}")
    #     window_obj.location[1] += neg_offset
    #     print(f"Negative location: {window_obj.location}")
    #     depsgraph = bpy.context.evaluated_depsgraph_get()
    #     depsgraph.update()
    #     neg_world_matrix = window_obj.matrix_world
    #     print(f"Negative world matrix: {neg_world_matrix.translation}")
    #     print(f"Room center: {room_center}")
    #     neg_distance = (neg_world_matrix.translation - room_center).length
        
    #     # Choose the offset that results in the window being closer to room center
    #     if pos_distance < neg_distance:
    #         wall_offset = pos_offset
    #         print(f"Window {window_obj.name} - Positive offset closer (dist: {pos_distance:.2f} vs {neg_distance:.2f}), using +{wall_offset}")
    #     else:
    #         wall_offset = neg_offset
    #         print(f"Window {window_obj.name} - Negative offset closer (dist: {neg_distance:.2f} vs {pos_distance:.2f}), using {wall_offset}")
        
    #     window_obj.location[1] += wall_offset
    #     print(f"Window {window_obj.name} location: {window_obj.location}")
    #     # window location is in world coordinates
    #     print(f"Window {window_obj.name} world location: {window_obj.matrix_world.translation}")
    #########################################################



    scene_preprocessed = placement.camera.camera_selection_preprocessing(
        terrain=None, scene_objs=scene_objs
    )

    if overrides.get("place_2", False):
        logger.info("Using --place_2 flag: Starting dual camera placement by reusing pose_cameras.")

        # === TUNABLE PARAMETERS ===
        MIN_INTERSECTION_FRAC = 0.05
        MAX_INTERSECTION_FRAC = 0.4
        MIN_UNION_FRAC = 0.6
        SAMPLING_RESOLUTION = 0.3
        MAX_SEARCH_TRIES = 5 #10

        #########################################################-------------
        MIN_INTERSECTION_COUNT = 1 #3
        MAX_INTERSECTION_COUNT = 50 #10
        #########################################################-------------

        room_bbox = solved_bbox
        def reusable_pose_cameras(rigs_to_pose):
            solved_floor_surface = butil.join_objects(
                [
                    tagging.extract_tagged_faces(o, {t.Subpart.SupportSurface})
                    for o in solved_rooms
                ]
            )

            poses = cam_traj.compute_poses(
                cam_rigs=rigs_to_pose,
                scene_preprocessed=scene_preprocessed,
                init_surfaces=solved_floor_surface,
                nonroom_objs=nonroom_objs,
            )
            butil.delete(solved_floor_surface)
            return poses

        logger.info("Placing Camera 1...")
        all_camera_rigs = placement.camera.spawn_camera_rigs(n_camera_rigs=2)
        cam_rig_1 = [all_camera_rigs[0]]
        cam_rig_2 = [all_camera_rigs[1]]

        cam1 = cam_rig_1[0].children[0]
        cam2 = cam_rig_2[0].children[0]

        ##### logger.info("Placing Camera 1...")
        ##### reusable_pose_cameras(cam_rig_1)
        ##### logger.info(f"Placed Camera 1 at {cam1.location.to_tuple(2)}")

        for i in range(MAX_SEARCH_TRIES):
            logger.info(f"Attempt {i+1}/{MAX_SEARCH_TRIES} to place Camera 2...")

            #########################################################-------------
            logger.info("Placing Cameras...")
            reusable_pose_cameras(cam_rig_1)
            #########################################################-------------
            reusable_pose_cameras(cam_rig_2)

            union_frac, intersection_frac = placement.camera.calculate_view_fractions(
                room_bbox, cam1, cam2, resolution=SAMPLING_RESOLUTION
            )
            logger.info(f"Candidate pose has union fraction: {union_frac:.2%}")
            logger.info(f"Candidate pose has intersection fraction: {intersection_frac:.2%}")

            #########################################################-------------
            print("=========================########################################################===========================")
            objects_visible_cam1, objects_visible_cam2 = placement.camera.get_visible_objects_per_camera(cam1, cam2)
            set_cam1 = set(objects_visible_cam1)
            set_cam2 = set(objects_visible_cam2)
            intersection_set = set_cam1 & set_cam2
            intersection_count = len(intersection_set)
            #########################################################-------------

            #########################################################
            if union_frac >= MIN_UNION_FRAC and intersection_frac <= MAX_INTERSECTION_FRAC and intersection_frac >= MIN_INTERSECTION_FRAC:
            #####    logger.info(f"SUCCESS! Found valid pose for Camera 2 with desired intersection.")
            #####    break

            #########################################################-------------
                logger.info("Volume fraction OK. Proceeding to detailed object visibility check...")

                # --- STAGE 2: Detailed check using visible object count ---
                # This part only runs if the first check passed
                objects_visible_cam1, objects_visible_cam2 = placement.camera.get_visible_objects_per_camera(cam1, cam2)

                intersection_set = set(objects_visible_cam1) & set(objects_visible_cam2)
                intersection_count = len(intersection_set)
                print(f"Objects visible from Camera 1: {objects_visible_cam1}")
                print(f"Objects visible from Camera 2: {objects_visible_cam2}")


                logger.info(f"Found {intersection_count} shared visible objects.")

                # Check if the object count is within the desired range
                if MIN_INTERSECTION_COUNT <= intersection_count <= MAX_INTERSECTION_COUNT:
                    logger.info(f"SUCCESS! Found valid pose satisfying all criteria.")
                    logger.info(f"  - Volume Fraction: {intersection_frac:.2%}")
                    logger.info(f"  - Shared Objects: {intersection_count}")
                    break
                else:
                    logger.warning(f"  - Failed object count check (Count: {intersection_count}, Required: [{MIN_INTERSECTION_COUNT}-{MAX_INTERSECTION_COUNT}]).")
            else:
                logger.warning(f"  - Failed union fraction check (Fraction: {union_frac:.2%}, Required: [>{MIN_UNION_FRAC:.2%}.")
                logger.warning(f"  - Failed volume fraction check (Fraction: {intersection_frac:.2%}, Required: [{MIN_INTERSECTION_FRAC:.2%}-{MAX_INTERSECTION_FRAC:.2%}]).")
            #########################################################-------------



            #########################################################
            # if MIN_INTERSECTION_FRAC <= intersection_frac <= MAX_INTERSECTION_FRAC:
            #     logger.info(f"SUCCESS! Found valid pose for Camera 2 with desired intersection.")
            #     break
            #########################################################
        else:
            #########################################################-------------
            butil.delete(cam_rig_1)
            #########################################################-------------
            butil.delete(cam_rig_2)
            raise RuntimeError(f"Failed to find a suitable pose for Camera 2 after {MAX_SEARCH_TRIES} tries.")
        camera_rigs = cam_rig_1 + cam_rig_2

    else:
        logger.info("Default behavior: Posing and animating multiple cameras.")
        camera_rigs = placement.camera.spawn_camera_rigs()

        def pose_cameras():
            solved_floor_surface = butil.join_objects(
                [
                    tagging.extract_tagged_faces(o, {t.Subpart.SupportSurface})
                    for o in solved_rooms
                ]
            )
            poses = cam_traj.compute_poses(
                cam_rigs=camera_rigs,
                scene_preprocessed=scene_preprocessed,
                init_surfaces=solved_floor_surface,
                nonroom_objs=nonroom_objs,
            )
            butil.delete(solved_floor_surface)
            return poses, scene_preprocessed

        poses, _ = p.run_stage(
            "pose_cameras", pose_cameras, use_chance=False, default=(None, None)
        )

        def animate_cameras():
            cam_traj.animate_trajectories(
                cam_rigs=camera_rigs,
                base_views=poses,
                scene_preprocessed=scene_preprocessed,
                obj_groups=[room_objs, nonroom_objs],
            )
            frames_folder = output_folder.parent / "frames"
            animated_cams = [cam for cam in camera_rigs if cam.animation_data is not None]
            save_imu_tum_files(frames_folder / "imu_tum", animated_cams)

        p.run_stage(
            "animate_cameras", animate_cameras, use_chance=False, prereq="pose_cameras"
        )

    p.run_stage(
        "populate_intermediate_pholders",
        populate.populate_state_placeholders,
        solver.state,
        filter=t.Semantics.AssetPlaceholderForChildren,
        final=False,
        use_chance=False,
    )

    def solve_medium():
        solve_stage_name("on_wall", "medium")
        solve_stage_name("on_ceiling", "medium")
        solve_stage_name("side_obj", "medium")

    p.run_stage("solve_medium", solve_medium, use_chance=False, default=state)

    def solve_small():
        solve_stage_name("obj_ontop_obj", "small", addition_weight_scalar=3)
        solve_stage_name("obj_on_support", "small", restrict_moves=["addition"])

    p.run_stage("solve_small", solve_small, use_chance=False, default=state)

    solver.optim.save_stats(output_folder / "optim_records.csv")

    p.run_stage(
        "populate_assets", populate.populate_state_placeholders, state, use_chance=False
    )

    def place_floating():
        pholder_rooms = butil.get_collection("placeholders:room_meshes")
        pholder_cutters = butil.get_collection("placeholders:portal_cutters")
        pholder_objs = butil.get_collection("placeholders")

        obj_fac_names = load_txt_list(
            repo_root() / "tests" / "assets" / "list_indoor_meshes.txt"
        )
        facs = [import_item(path) for path in obj_fac_names]

        placer = FloatingObjectPlacement(
            generators=facs,
            camera=camera_rigs[0].children[0],
            background_objs=list(pholder_cutters.objects) + list(pholder_rooms.objects),
            collision_objs=list(pholder_objs.objects),
        )

        placer.place_objs(
            num_objs=overrides.get("num_floating", 20),
            normalize=overrides.get("norm_floating_size", True),
            collision_placed=overrides.get("enable_collision_floating", False),
            collision_existing=overrides.get("enable_collision_solved", False),
        )

    p.run_stage("floating_objs", place_floating, use_chance=False, default=state)

    door_filter = r.Domain({t.Semantics.Door}, [(cl.AnyRelation(), stages["rooms"])])
    window_filter = r.Domain(
        {t.Semantics.Window}, [(cl.AnyRelation(), stages["rooms"])]
    )
    p.run_stage(
        "room_doors",
        lambda: room_dec.populate_doors(solver.get_bpy_objects(door_filter), constants),
        use_chance=False,
    )
    p.run_stage(
        "room_windows",
        lambda: room_dec.populate_windows(
            solver.get_bpy_objects(window_filter), constants, state
        ),
        use_chance=False,
    )

    room_meshes = solver.get_bpy_objects(r.Domain({t.Semantics.Room}))
    p.run_stage(
        "room_stairs",
        lambda: room_dec.room_stairs(constants, state, room_meshes),
        use_chance=False,
    )
    p.run_stage(
        "skirting_floor",
        lambda: make_skirting_board(constants, room_meshes, t.Subpart.SupportSurface),
    )
    p.run_stage(
        "skirting_ceiling",
        lambda: make_skirting_board(constants, room_meshes, t.Subpart.Ceiling),
    )

    rooms_meshed = butil.get_collection("placeholders:room_meshes")

    if overrides.get("enable_ocmesh_room", False):
        rooms_ocmeshed = []
        cameras = [cam for camera_rig in camera_rigs for cam in camera_rig.children]
        for room_meshed in rooms_meshed.objects:
            room_ocmeshed = ocmesher_utils.run_ocmesher(room_meshed, cameras)
            rooms_ocmeshed.append(room_ocmeshed)

        butil.group_in_collection(rooms_ocmeshed, "placeholders:room_ocmeshes")
        rooms_meshed = butil.get_collection("placeholders:room_ocmeshes")
        for mesh in rooms_meshed.objects:
            convert_shader_displacement(mesh)

    rooms_split = room_dec.split_rooms(list(rooms_meshed.objects))

    p.run_stage(
        "room_pillars",
        room_dec.room_pillars,
        rooms_split["wall"].objects,
        constants,
    )

    p.run_stage(
        "room_walls",
        room_dec.room_walls,
        rooms_split["wall"].objects,
        constants,
        use_chance=False,
    )
    p.run_stage(
        "room_floors",
        room_dec.room_floors,
        rooms_split["floor"].objects,
        use_chance=False,
    )
    p.run_stage(
        "room_ceilings",
        room_dec.room_ceilings,
        rooms_split["ceiling"].objects,
        use_chance=False,
    )

    # state.print()
    state.to_json(output_folder / "solve_state.json")

    def turn_off_lights():
        for o in bpy.data.objects:
            if o.type == "LIGHT" and not o.data.cycles.is_portal:
                print(f"Deleting {o.name}")
                butil.delete(o)

    p.run_stage("lights_off", turn_off_lights)

    def invisible_room_ceilings():
        invisible_to_camera = InvisibleToCamera()
        rooms_split["exterior"].hide_viewport = True
        rooms_split["exterior"].hide_render = True
        invisible_to_camera.apply(list(rooms_split["ceiling"].objects))
        invisible_to_camera.apply(
            [o for o in bpy.data.objects if "CeilingLight" in o.name]
        )

    p.run_stage("invisible_room_ceilings", invisible_room_ceilings, use_chance=False)

    p.run_stage(
        "overhead_cam",
        place_cam_overhead,
        cam=camera_rigs[0],
        bbox=solved_bbox,
        use_chance=False,
    )

    p.run_stage(
        "hide_other_rooms",
        hide_other_rooms,
        state,
        rooms_split,
        keep_rooms=[r.name for r in solved_rooms],
        use_chance=False,
    )

    height = p.run_stage(
        "nature_backdrop",
        create_outdoor_backdrop,
        terrain,
        house_bbox=house_bbox,
        cameras=[rig.children[0] for rig in camera_rigs],
        p=p,
        params=overrides,
        use_chance=False,
        prereq="terrain",
        default=0,
    )

    if overrides.get("topview", False):
        rooms_split["exterior"].hide_viewport = True
        rooms_split["ceiling"].hide_viewport = True
        rooms_split["exterior"].hide_render = True
        rooms_split["ceiling"].hide_render = True
        for group in ["wall", "floor"]:
            for wall in rooms_split[group].objects:
                for mat in wall.data.materials:
                    for n in mat.node_tree.nodes:
                        if n.type == "BSDF_PRINCIPLED":
                            n.inputs["Alpha"].default_value = overrides.get(
                                "alpha_walls", 1.0
                            )
        bbox = np.concatenate(
            [
                read_co(r) + np.array(r.location)[np.newaxis, :]
                for r in rooms_meshed.objects
            ]
        )
        camera = camera_rigs[0].children[0]
        camera_rigs[0].location = 0, 0, 0
        camera_rigs[0].rotation_euler = 0, 0, 0
        bpy.context.scene.camera = camera
        rot_x = np.deg2rad(overrides.get("topview_rot_x", 0))
        rot_z = np.deg2rad(overrides.get("topview_rot_z", 0))
        camera.rotation_euler = rot_x, 0, rot_z
        cam_x = (np.amax(bbox[:, 0]) + np.amin(bbox[:, 0])) / 2
        cam_y = (np.amax(bbox[:, 1]) + np.amin(bbox[:, 1])) / 2
        for cam_dist in np.exp(np.linspace(1.0, 5.0, 500)):
            camera.location = (
                cam_x + cam_dist * np.sin(rot_x) * np.sin(rot_z),
                cam_y - cam_dist * np.sin(rot_x) * np.cos(rot_z),
                cam_dist * np.cos(rot_x),
            )
            bpy.context.view_layer.update()
            inview = cam_util.points_inview(bbox, camera)
            if inview.all():
                for area in bpy.context.screen.areas:
                    if area.type == "VIEW_3D":
                        area.spaces.active.region_3d.view_perspective = "CAMERA"
                        break
                break

    p.save_results(output_folder / "pipeline_coarse.csv")

    return {
        "height_offset": height,
        "whole_bbox": house_bbox,
    }


def main(args):
    scene_seed = init.apply_scene_seed(args.seed)
    init.apply_gin_configs(
        configs=["base_indoors.gin"] + args.configs,
        overrides=args.overrides,
        config_folders=[
            "infinigen_examples/configs_indoor",
            "infinigen_examples/configs_nature",
        ],
    )

    execute_tasks.main(
        compose_scene_func=compose_indoors,
        populate_scene_func=None,
        input_folder=args.input_folder,
        output_folder=args.output_folder,
        task=args.task,
        task_uniqname=args.task_uniqname,
        scene_seed=scene_seed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_folder", type=Path)
    parser.add_argument("--input_folder", type=Path, default=None)
    parser.add_argument(
        "-s", "--seed", default=None, help="The seed used to generate the scene"
    )
    parser.add_argument(
        "-t",
        "--task",
        nargs="+",
        default=["coarse"],
        choices=[
            "coarse",
            "populate",
            "fine_terrain",
            "ground_truth",
            "render",
            "mesh_save",
            "export",
        ],
    )
    parser.add_argument(
        "-g",
        "--configs",
        nargs="+",
        default=["base"],
        help="Set of config files for gin (separated by spaces) "
        "e.g. --gin_config file1 file2 (exclude .gin from path)",
    )
    parser.add_argument(
        "--place_2",
        action="store_true",
        help="Use dual camera placement with volumetric intersection."
    )

    parser.add_argument(
        "-p",
        "--overrides",
        nargs="+",
        default=[],
        help="Parameter settings that override config defaults "
        "e.g. --gin_param module_1.a=2 module_2.b=3",
    )
    parser.add_argument("--task_uniqname", type=str, default=None)
    parser.add_argument("-d", "--debug", type=str, nargs="*", default=None)

    args = init.parse_args_blender(parser)

    logging.getLogger("infinigen").setLevel(logging.INFO)
    logging.getLogger("infinigen.core.nodes.node_wrangler").setLevel(logging.CRITICAL)

    if args.debug is not None:
        for name in logging.root.manager.loggerDict:
            if not name.startswith("infinigen"):
                continue
            if len(args.debug) == 0 or any(name.endswith(x) for x in args.debug):
                logging.getLogger(name).setLevel(logging.DEBUG)

    main(args)

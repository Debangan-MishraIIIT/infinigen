# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

import argparse
import logging
from pathlib import Path

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
from infinigen.assets.composition.material_logger import init_material_logger
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
    p = pipeline.RandomStageExecutor(scene_seed, output_folder, overrides)
    
    # Initialize material logger
    init_material_logger(output_folder)

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

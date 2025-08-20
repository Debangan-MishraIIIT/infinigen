# re_pose_cameras.py
import argparse
import logging
from pathlib import Path
import bpy
import gin

# Ensure infinigen is in your Python path
from infinigen.core import init, placement, tagging
from infinigen.core import tags as t
from infinigen.core.placement import camera_trajectories as cam_traj
from infinigen.core.util import blender as butil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def delete_existing_camera_rigs():
    """Finds and deletes all objects in the 'camera_rigs' collection."""
    if "camera_rigs" not in bpy.data.collections:
        logger.info("No 'camera_rigs' collection found, nothing to delete.")
        return

    rig_collection = bpy.data.collections["camera_rigs"]
    objects_to_delete = list(rig_collection.objects)

    if not objects_to_delete:
        logger.info("'camera_rigs' collection is empty.")
        return

    logger.info(f"Deleting {len(objects_to_delete)} existing camera rigs...")
    with butil.SelectObjects(objects_to_delete):
        bpy.ops.object.delete()

def reconstruct_scene_vars():
    """Inspects the loaded scene to rebuild lists of important objects."""
    all_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    room_objs = [o for o in all_objs if t.Semantics.Room in tagging.get_tags(o)]
    nonroom_objs = [o for o in all_objs if t.Semantics.Room not in tagging.get_tags(o)]

    logger.info(f"Reconstructed scene: Found {len(room_objs)} rooms and {len(nonroom_objs)} other objects.")
    return room_objs, nonroom_objs, room_objs + nonroom_objs

def re_pose_cameras(args):
    """The main function to delete old cameras and place new ones."""

    # 1. Load the user's .blend file
    logger.info(f"Loading scene from {args.input_blend}")
    bpy.ops.wm.open_mainfile(filepath=str(args.input_blend))

    # 2. Delete any cameras that might already be there
    delete_existing_camera_rigs()

    # 3. Re-create the necessary Python variables by inspecting the scene
    solved_rooms, nonroom_objs, scene_objs = reconstruct_scene_vars()

    # 4. Use the PREEXISTING logic to place new cameras
    logger.info("Using preexisting logic to place new cameras...")

    # Pre-computation step, same as in your main script
    scene_preprocessed = placement.camera.camera_selection_preprocessing(
        terrain=None, scene_objs=scene_objs
    )

    # Create a new set of camera rigs to be placed
    camera_rigs = placement.camera.spawn_camera_rigs()

    # This is the same core logic from your `pose_cameras` function
    solved_floor_surface = butil.join_objects(
        [
            tagging.extract_tagged_faces(o, {t.Subpart.SupportSurface})
            for o in solved_rooms
        ]
    )
    cam_traj.compute_poses(
        cam_rigs=camera_rigs,
        scene_preprocessed=scene_preprocessed,
        init_surfaces=solved_floor_surface,
        nonroom_objs=nonroom_objs,
    )
    butil.delete(solved_floor_surface)

    logger.info(f"Successfully placed {len(camera_rigs)} new camera rigs.")

    # 5. Save the modified scene to a new file
    output_path = args.output_folder / f"{args.input_blend.stem}_with_new_cameras.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    logger.info(f"Saved modified scene to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_blend", type=Path, required=True, help="Path to the .blend file to modify.")
    parser.add_argument("--output_folder", type=Path, required=True, help="Folder to save the new .blend file in.")

    # This uses the same parser from the Infinigen framework
    args = init.parse_args_blender(parser)

    re_pose_cameras(args)

# python -m infinigen_examples.generate_indoors --seed 0 --task coarse --output_folder outputs/indoors/coarse -g fast_solve.gin singleroom.gin -p compose_indoors.terrain_enabled=False restrict_solving.restrict_parent_rooms=\[\"DiningRoom\"\] compose_indoors.place_2=True
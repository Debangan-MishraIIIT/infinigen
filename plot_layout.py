import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Rectangle, FancyBboxPatch
import numpy as np
from shapely.geometry import box, LineString
import shapely

def parse_shapely_shape(shape_str):
    """Parse shapely shape string and return the geometry object"""
    try:
        # Remove 'shapely.' prefix and evaluate
        shape_code = shape_str.replace('shapely.', '')
        return eval(shape_code)
    except Exception as e:
        print(f"Error parsing shape: {shape_str}, Error: {e}")
        return None

def plot_floor_plan(json_file_path, output_file=None, show_plot=True):
    """
    Plot floor plan from JSON configuration file
    
    Args:
        json_file_path (str): Path to the JSON configuration file
        output_file (str, optional): Path to save the plot image
        show_plot (bool): Whether to display the plot
    """
    
    # Load JSON configuration
    with open(json_file_path, 'r') as f:
        config = json.load(f)
    
    # Create figure and axis
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    
    # Plot rooms
    room_colors = {
        'living-room': '#FFE4B5',  # Light orange
        'dining-room': '#F0E68C',  # Khaki
        'kitchen': '#98FB98',      # Pale green
        'bedroom': '#DDA0DD',      # Plum
        'bathroom': '#87CEEB'      # Sky blue
    }
    
    print("Plotting rooms...")
    for room_name, room_data in config['rooms'].items():
        shape_str = room_data['shape']
        shape = parse_shapely_shape(shape_str)
        
        if shape is not None:
            # Extract coordinates for plotting
            if hasattr(shape, 'bounds'):
                minx, miny, maxx, maxy = shape.bounds
                width = maxx - minx
                height = maxy - miny
                
                # Get room type for color
                room_type = room_name.split('_')[0]
                color = room_colors.get(room_type, '#CCCCCC')
                
                # Create rectangle patch
                rect = Rectangle((minx, miny), width, height, 
                               facecolor=color, edgecolor='black', 
                               linewidth=2, alpha=0.7)
                ax.add_patch(rect)
                
                # Add room label
                center_x = minx + width/2
                center_y = miny + height/2
                ax.text(center_x, center_y, room_type.replace('-', '\n'), 
                       ha='center', va='center', fontsize=10, fontweight='bold')
                
                print(f"  - {room_name}: {shape_str}")
    
    # Plot doors
    print("Plotting doors...")
    for door_name, door_data in config['doors'].items():
        shape_str = door_data['shape']
        shape = parse_shapely_shape(shape_str)
        
        if shape is not None:
            if hasattr(shape, 'coords'):
                coords = list(shape.coords)
                if len(coords) >= 2:
                    x_coords = [coord[0] for coord in coords]
                    y_coords = [coord[1] for coord in coords]
                    
                    # Plot door as a thick line
                    ax.plot(x_coords, y_coords, color='brown', linewidth=8, 
                           solid_capstyle='round', label='Door')
                    
                    # Add door label
                    mid_x = sum(x_coords) / len(x_coords)
                    mid_y = sum(y_coords) / len(y_coords)
                    ax.text(mid_x, mid_y, 'D', ha='center', va='center', 
                           fontsize=8, fontweight='bold', color='white')
                    
                    print(f"  - {door_name}: {shape_str}")
    
    # Plot windows
    print("Plotting windows...")
    for window_name, window_data in config['windows'].items():
        shape_str = window_data['shape']
        shape = parse_shapely_shape(shape_str)
        
        if shape is not None:
            if hasattr(shape, 'coords'):
                coords = list(shape.coords)
                if len(coords) >= 2:
                    x_coords = [coord[0] for coord in coords]
                    y_coords = [coord[1] for coord in coords]
                    
                    # Plot window as a thin line
                    ax.plot(x_coords, y_coords, color='blue', linewidth=3, 
                           solid_capstyle='round', label='Window')
                    
                    # Add window label
                    mid_x = sum(x_coords) / len(x_coords)
                    mid_y = sum(y_coords) / len(y_coords)
                    ax.text(mid_x, mid_y, 'W', ha='center', va='center', 
                           fontsize=8, fontweight='bold', color='white')
                    
                    print(f"  - {window_name}: {shape_str}")
    
    # Set plot properties
    ax.set_xlabel('X Coordinate (meters)', fontsize=12)
    ax.set_ylabel('Y Coordinate (meters)', fontsize=12)
    ax.set_title('Floor Plan Layout', fontsize=16, fontweight='bold')
    
    # Set equal aspect ratio and grid
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)
    
    # Set axis limits with some padding
    ax.set_xlim(-1, 16)
    ax.set_ylim(-1, 15)
    
    # Create custom legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='brown', linewidth=8, label='Doors'),
        Line2D([0], [0], color='blue', linewidth=3, label='Windows'),
        patches.Patch(color='#FFE4B5', label='Living Room'),
        patches.Patch(color='#F0E68C', label='Dining Room'),
        patches.Patch(color='#98FB98', label='Kitchen'),
        patches.Patch(color='#DDA0DD', label='Bedroom'),
        patches.Patch(color='#87CEEB', label='Bathroom')
    ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.15, 1))
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Save plot if output file specified
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")
    
    # Show plot
    if show_plot:
        plt.show()
    
    return fig, ax

def main():
    """Main function to run the floor plan plotting"""
    # Path to the JSON configuration file
    json_file = "infinigen_examples/configs_indoor/floor_plans/new_v2.json"
    
    try:
        # Plot the floor plan
        fig, ax = plot_floor_plan(json_file, output_file="floor_plan.png")
        print("Floor plan plotting completed successfully!")
        
    except FileNotFoundError:
        print(f"Error: Could not find the JSON file at {json_file}")
        print("Please make sure the file path is correct.")
    except Exception as e:
        print(f"Error plotting floor plan: {e}")

if __name__ == "__main__":
    main()

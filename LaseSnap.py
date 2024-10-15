import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pyvisa
import serial.tools.list_ports
import os
import shutil
import time
from datetime import datetime
import spectral.io.envi as envi
import spectral as spy
from PIL import Image, ImageTk, ImageOps  # For image display
import logging
import numpy as np  # For cube summation

# Global variables for snapshot comparison and project information
before_snapshot = []
experiment_finished = False
project_name = ""
output_path = ""
saved_images_directory = r'C:\BaySpec\GoldenEye\saved_images'

selected_images = []
loaded_cubes = []
available_wavelengths = set()  # To store unique wavelengths

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def check_tls_device():
    try:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        logging.info(f"VISA Resources found: {resources}")
        if not resources:
            logging.info("No VISA resources found.")
            return False, None

        for resource in resources:
            try:
                device = rm.open_resource(resource)
                logging.info(f"Device Query: {device.query('*IDN?')}")
                if "CS130B" in device.query('*IDN?'):
                    logging.info(f"TLS device found at {resource}")
                    return True, resource
            except pyvisa.VisaIOError:
                continue

        logging.info("TLS device not found.")
        return False, None

    except pyvisa.VisaIOError as e:
        logging.error(f"Error accessing VISA resources: {e}")
        return False, None


def check_arduino_device():
    try:
        ports = list(serial.tools.list_ports.comports())
        logging.info(f"Available serial ports: {ports}")
        if not ports:
            logging.info("No serial ports found.")
            return False, None

        for port in ports:
            logging.info(f"Port Description: {port.description}")
            if "Arduino" in port.description or "CP210" in port.description:
                logging.info(f"Arduino found at {port.device}")
                return True, port.device

        logging.info("Arduino device not found.")
        return False, None

    except Exception as e:
        logging.error(f"Error accessing serial ports: {e}")
        return False, None


def sort_folders_by_modification(folders):
    folders_with_time = [(folder, os.path.getmtime(os.path.join(saved_images_directory, folder))) for folder in folders]
    sorted_folders = sorted(folders_with_time, key=lambda x: x[1])
    return [folder[0] for folder in sorted_folders]


def take_snapshot():
    global before_snapshot
    before_snapshot = os.listdir(saved_images_directory)
    logging.info(f"Initial snapshot taken: {before_snapshot}")


def find_tls():
    global tls_found, tls_device_address
    tls_found, tls_device_address = check_tls_device()

    if tls_found:
        tls_status_label.config(bg='green')
        find_tls_button.config(state='disabled')
        check_device_status()
    else:
        tls_status_label.config(bg='red')
        messagebox.showerror("Error", "TLS device not found")


def find_golden_eye():
    global golden_eye_found, arduino_port
    golden_eye_found, arduino_port = check_arduino_device()

    if golden_eye_found:
        golden_eye_status_label.config(bg='green')
        find_golden_eye_button.config(state='disabled')
        check_device_status()
    else:
        golden_eye_status_label.config(bg='red')
        messagebox.showerror("Error", "Golden Eye (Arduino) device not found")


def check_device_status():
    if tls_found and golden_eye_found:
        execute_button.config(state='normal')


def execute_commands():
    global experiment_finished
    rm = pyvisa.ResourceManager()
    device = rm.open_resource(tls_device_address)
    device.timeout = 6000
    take_snapshot()

    for child in tree.get_children():
        wavelength = tree.item(child)["values"][0]
        num_pictures = tree.item(child)["values"][1]

        for i in range(num_pictures):
            device.write(f'gowave {wavelength}')
            logging.info(f"TLS Command Sent: gowave {wavelength}")
            time.sleep(5)

            send_trigger()
            logging.info("Arduino Triggered")
            time.sleep(10)

    experiment_finished = True
    process_button.config(state='normal')


def add_row():
    wavelength = wavelength_entry.get()
    num_pictures = pictures_entry.get()
    tree.insert("", "end", values=(wavelength, num_pictures))


def send_trigger():
    baud_rate = 9600
    with serial.Serial(arduino_port, baud_rate, timeout=1) as ser:
        time.sleep(2)
        ser.write(trigger_string.encode('utf-8'))
        logging.info(f"Sent: {trigger_string.strip()}")


def process_results():
    if not experiment_finished:
        messagebox.showerror("Error", "Experiment is not finished yet!")
        return

    after_snapshot = os.listdir(saved_images_directory)
    logging.info(f"New snapshot taken: {after_snapshot}")

    new_folders = list(set(after_snapshot) - set(before_snapshot))
    new_folders_sorted = sort_folders_by_modification(new_folders)
    logging.info(f"Sorted new folders: {new_folders_sorted}")

    total_pictures = sum(int(tree.item(child)["values"][1]) for child in tree.get_children())
    logging.info(f"Total pictures expected: {total_pictures}")

    if len(new_folders_sorted) == total_pictures:
        open_project_window(new_folders_sorted)
        add_cubes_for_same_wavelength(new_folders_sorted)
    else:
        messagebox.showerror("Error", f"Expected {total_pictures} folders, but found {len(new_folders_sorted)} new folders.")


def add_cubes_for_same_wavelength(folders):
    date_str = datetime.now().strftime("%m-%d")

    wavelength_dict = {}
    for folder in folders:
        parts = folder.split('_')
        if len(parts) >= 3:
            wavelength = parts[2]
            if wavelength not in wavelength_dict:
                wavelength_dict[wavelength] = []
            wavelength_dict[wavelength].append(folder)

    for wavelength, folders in wavelength_dict.items():
        combined_cube = None
        first_hdr_metadata = None

        for folder in folders:
            hdr_path = os.path.join(saved_images_directory, folder, 'spectral_image_processed_image.hdr')
            bin_path = os.path.join(saved_images_directory, folder, 'spectral_image_processed_image.bin')

            cube = envi.open(hdr_path, bin_path)
            cube_data = cube.load()

            if first_hdr_metadata is None:
                first_hdr_metadata = cube.metadata

            if combined_cube is None:
                combined_cube = cube_data
            else:
                assert combined_cube.shape == cube_data.shape, f"Cubes must have the same dimensions: {folder}"
                combined_cube += cube_data

        rgb_bands = (29, 19, 9)
        output_rgb_file = os.path.join(output_path, f'{project_name}_{date_str}_{wavelength}_combined.png')
        spy.save_rgb(output_rgb_file, combined_cube, rgb_bands)
        logging.info(f"Saved combined RGB image for wavelength {wavelength} at {output_rgb_file}")

        output_hdr_file = os.path.join(output_path, f'{project_name}_{date_str}_{wavelength}_union.hdr')
        envi.save_image(output_hdr_file, combined_cube, metadata=first_hdr_metadata, force=True)
        logging.info(f"Saved combined cube for wavelength {wavelength} at {output_hdr_file}")


def open_project_window(new_folders_sorted):
    def select_output_folder():
        selected_folder = filedialog.askdirectory()
        if selected_folder:
            output_path_label.config(text=selected_folder)
            global output_path
            output_path = selected_folder

    def save_project_info():
        global project_name, output_path
        project_name = project_name_entry.get()

        if not project_name or not output_path:
            messagebox.showerror("Error", "Please provide both project name and output path.")
            return

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        rename_and_copy_folders(new_folders_sorted)
        project_window.destroy()

    project_window = tk.Toplevel(root)
    project_window.title("Project Details")
    project_window.geometry("500x200")

    tk.Label(project_window, text="Project Name:").pack(pady=5)
    project_name_entry = tk.Entry(project_window)
    project_name_entry.pack(pady=5)

    tk.Label(project_window, text="Output Folder:").pack(pady=5)

    output_path_label = tk.Label(project_window, text="No folder selected", relief=tk.SUNKEN, width=40)
    output_path_label.pack(pady=5)
    tk.Button(project_window, text="Browse", command=select_output_folder).pack(pady=5)

    tk.Button(project_window, text="Save", command=save_project_info).pack(pady=10)


def rename_and_copy_folders(new_folders_sorted):
    date_str = datetime.now().strftime("%m-%d")
    current_index = 0

    for child in tree.get_children():
        wavelength = tree.item(child)["values"][0]
        num_pictures = int(tree.item(child)["values"][1])

        for i in range(1, num_pictures + 1):
            new_name = f"{project_name}_{date_str}_{wavelength}_{i}"
            old_folder = os.path.join(saved_images_directory, new_folders_sorted[current_index])
            new_folder = os.path.join(output_path, new_name)

            shutil.copytree(old_folder, new_folder)
            logging.info(f"Copied and renamed folder: {old_folder} -> {new_folder}")

            current_index += 1

    messagebox.showinfo("Success", "Folders copied and renamed successfully!")


# ----------- Processing Tab Functions -----------

loaded_images = []


# Function to load the folder and display **all images** found in the folder
def load_folder():
    folder_path = filedialog.askdirectory()

    if folder_path:
        logging.info(f"Folder selected: {folder_path}")
        # Convert and display all the images found in the folder
        load_and_display_cubes(folder_path)


# Function to handle checkbox selection
def toggle_image_selection(index, var):
    if var.get():  # If the checkbox is checked
        if index not in selected_images:
            selected_images.append(index)
    else:  # If the checkbox is unchecked
        if index in selected_images:
            selected_images.remove(index)

    logging.info(f"Selected Images: {selected_images}")

    # Enable or disable the "Sum Cubes" button depending on selections
    if selected_images:
        sum_cubes_button.config(state="normal")
    else:
        sum_cubes_button.config(state="disabled")


# Function to load cubes and display images
# def load_and_display_cubes(folder_path):
#     # Clear previous images
#     for widget in image_panel_frame.winfo_children():
#         widget.destroy()
#
#     # Clear previous cubes, selections, and wavelengths
#     loaded_cubes.clear()
#     selected_images.clear()
#     sum_cubes_button.config(state="disabled")
#     available_wavelengths.clear()
#
#     subfolders = [f.path for f in os.scandir(folder_path) if f.is_dir()]
#     total_subfolders = len(subfolders)
#
#     if total_subfolders == 0:
#         logging.warning("No subfolders found in the selected folder.")
#         progress_label.config(text="Loaded 0 of 0 subfolders")
#         return
#
#     logging.info(f"Found {total_subfolders} subfolders.")
#
#     loaded_folders = 0  # Track the number of folders processed
#
#     # Loop through each subfolder and process the hyperspectral images
#     for subfolder in subfolders:
#         folder_name = os.path.basename(subfolder)
#         parts = folder_name.split('_')
#
#         if len(parts) >= 3:
#             wavelength = parts[2]  # Extract wavelength from the folder name
#             i = parts[3] if len(parts) > 3 else "1"  # Extract i or default to 1
#
#             hdr_path = os.path.join(subfolder, 'spectral_image_processed_image.hdr')
#             bin_path = os.path.join(subfolder, 'spectral_image_processed_image.bin')
#
#             if os.path.exists(hdr_path) and os.path.exists(bin_path):
#                 logging.info(f"Loading hyperspectral cube from: {hdr_path} and {bin_path}")
#                 try:
#                     # Load the cube using spectral.io.envi
#                     meta_cube = envi.open(hdr_path, bin_path)
#                     cube = meta_cube.load()
#
#                     # Store the cube data and metadata for later use
#                     loaded_cubes.append((cube, meta_cube.metadata, wavelength, i))
#                     available_wavelengths.add(wavelength)  # Track unique wavelengths
#
#                     # Define the RGB bands
#                     rgb_bands = (29, 19, 9)  # Adjust these bands as needed
#
#                     # Save the RGB image
#                     output_rgb_image = os.path.join(subfolder, 'rgb_image.png')
#                     spy.save_rgb(output_rgb_image, cube, rgb_bands)
#                     logging.info(f"RGB image saved at: {output_rgb_image}")
#
#                     # Display the image
#                     img = Image.open(output_rgb_image)
#                     img = img.resize((300, 200), Image.Resampling.LANCZOS)
#                     img_tk = ImageTk.PhotoImage(img)
#
#                     # Store the image to prevent garbage collection
#                     loaded_images.append(img_tk)
#
#                     # Create a frame for each image, its label, and checkbox
#                     image_frame = tk.Frame(image_panel_frame)
#                     image_frame.pack(side=tk.LEFT, padx=10, pady=10)
#
#                     # Display the image in the frame
#                     img_label = tk.Label(image_frame, image=img_tk)
#                     img_label.pack()
#
#                     # Create a variable to track the checkbox state
#                     checkbox_var = tk.BooleanVar()
#
#                     # Create a checkbox next to the image name and make it selectable
#                     checkbox = tk.Checkbutton(image_frame, text=f'{wavelength}_{i}', variable=checkbox_var,
#                                               onvalue=True, offvalue=False,
#                                               command=lambda idx=len(loaded_cubes) - 1,
#                                                              var=checkbox_var: toggle_image_selection(idx, var))
#                     checkbox.pack(pady=5)
#
#                     # Update the progress after each subfolder is processed
#                     loaded_folders += 1
#                     progress_label.config(text=f"Loaded {loaded_folders} of {total_subfolders} subfolders")
#                     root.update_idletasks()
#
#                 except Exception as e:
#                     logging.error(f"Error loading or processing cube: {e}")
#             else:
#                 logging.warning(f"Hyperspectral files not found in {subfolder}")
#
#     # Final update to the progress label in case all subfolders were processed
#     progress_label.config(text=f"Loaded {loaded_folders} of {total_subfolders} subfolders")
#
#     # Update the wavelength filter dropdown with the available wavelengths
#     update_wavelength_filter()


# Function to update the wavelength filter dropdown
def update_wavelength_filter():
    wavelength_filter['values'] = ['No Filter'] + list(available_wavelengths)
    wavelength_filter.set('No Filter')  # Set default to 'No Filter'


def load_and_display_cubes(folder_path):
    # Clear previous images
    for widget in image_panel_frame.winfo_children():
        widget.destroy()

    # Clear previous cubes, selections, and wavelengths
    loaded_cubes.clear()
    selected_images.clear()
    sum_cubes_button.config(state="disabled")
    available_wavelengths.clear()

    subfolders = [f.path for f in os.scandir(folder_path) if f.is_dir()]
    total_subfolders = len(subfolders)

    if total_subfolders == 0:
        logging.warning("No subfolders found in the selected folder.")
        progress_label.config(text="Loaded 0 of 0 subfolders")
        return

    logging.info(f"Found {total_subfolders} subfolders.")

    loaded_folders = 0  # Track the number of folders processed

    # Loop through each subfolder and process the hyperspectral images
    for subfolder in subfolders:
        folder_name = os.path.basename(subfolder)
        parts = folder_name.split('_')

        if len(parts) >= 3:
            wavelength = parts[2]  # Extract wavelength from the folder name
            i = parts[3] if len(parts) > 3 else "1"  # Extract i or default to 1

            hdr_path = os.path.join(subfolder, 'spectral_image_processed_image.hdr')
            bin_path = os.path.join(subfolder, 'spectral_image_processed_image.bin')

            if os.path.exists(hdr_path) and os.path.exists(bin_path):
                logging.info(f"Loading hyperspectral cube from: {hdr_path} and {bin_path}")
                try:
                    # Load the cube using spectral.io.envi
                    meta_cube = envi.open(hdr_path, bin_path)
                    cube = meta_cube.load()

                    # Define the RGB bands
                    rgb_bands = (29, 19, 9)  # Adjust these bands as needed

                    # Save the RGB image
                    output_rgb_image = os.path.join(subfolder, 'rgb_image.png')
                    spy.save_rgb(output_rgb_image, cube, rgb_bands)
                    logging.info(f"RGB image saved at: {output_rgb_image}")

                    # Store the cube data and metadata, along with the path to the RGB image
                    loaded_cubes.append((cube, meta_cube.metadata, wavelength, i, output_rgb_image))
                    available_wavelengths.add(wavelength)  # Track unique wavelengths

                    # Display the image
                    img = Image.open(output_rgb_image)
                    img = img.resize((300, 200), Image.Resampling.LANCZOS)
                    img_tk = ImageTk.PhotoImage(img)

                    # Store the image to prevent garbage collection
                    loaded_images.append(img_tk)

                    # Create a frame for each image, its label, and checkbox
                    image_frame = tk.Frame(image_panel_frame)
                    image_frame.pack(side=tk.LEFT, padx=10, pady=10)

                    # Display the image in the frame
                    img_label = tk.Label(image_frame, image=img_tk)
                    img_label.pack()

                    # Create a variable to track the checkbox state
                    checkbox_var = tk.BooleanVar()

                    # Create a checkbox next to the image name and make it selectable
                    checkbox = tk.Checkbutton(image_frame, text=f'{wavelength}_{i}', variable=checkbox_var,
                                              onvalue=True, offvalue=False,
                                              command=lambda idx=len(loaded_cubes) - 1,
                                                             var=checkbox_var: toggle_image_selection(idx, var))
                    checkbox.pack(pady=5)

                    # Update the progress after each subfolder is processed
                    loaded_folders += 1
                    progress_label.config(text=f"Loaded {loaded_folders} of {total_subfolders} subfolders")
                    root.update_idletasks()

                except Exception as e:
                    logging.error(f"Error loading or processing cube: {e}")
            else:
                logging.warning(f"Hyperspectral files not found in {subfolder}")

    # Final update to the progress label in case all subfolders were processed
    progress_label.config(text=f"Loaded {loaded_folders} of {total_subfolders} subfolders")

    # Update the wavelength filter dropdown with the available wavelengths
    update_wavelength_filter()


# Function to filter the displayed images by wavelength
def filter_images():
    selected_wavelength = wavelength_filter.get()

    # If 'No Filter' is selected, display all images
    if selected_wavelength == 'No Filter':
        # Clear the current image panel
        for widget in image_panel_frame.winfo_children():
            widget.destroy()

        # Display all loaded images
        for idx, (cube, _, wavelength, i, output_rgb_image) in enumerate(loaded_cubes):
            if os.path.exists(output_rgb_image):
                img = Image.open(output_rgb_image)
                img = img.resize((300, 200), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(img)

                # Store the image to prevent garbage collection
                loaded_images.append(img_tk)

                # Create a frame for each image, its label, and checkbox
                image_frame = tk.Frame(image_panel_frame)
                image_frame.pack(side=tk.LEFT, padx=10, pady=10)

                # Display the image in the frame
                img_label = tk.Label(image_frame, image=img_tk)
                img_label.pack()

                # Create a variable to track the checkbox state
                checkbox_var = tk.BooleanVar()

                # Create a checkbox next to the image name and make it selectable
                checkbox = tk.Checkbutton(image_frame, text=f'{wavelength}_{i}', variable=checkbox_var,
                                          onvalue=True, offvalue=False,
                                          command=lambda idx=idx, var=checkbox_var: toggle_image_selection(idx, var))
                checkbox.pack(pady=5)
        return

    # Clear the current image panel if filtering by wavelength
    for widget in image_panel_frame.winfo_children():
        widget.destroy()

    # Display only the images that match the selected wavelength
    for idx, (cube, _, wavelength, i, output_rgb_image) in enumerate(loaded_cubes):
        if wavelength == selected_wavelength:
            if os.path.exists(output_rgb_image):
                img = Image.open(output_rgb_image)
                img = img.resize((300, 200), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(img)

                # Store the image to prevent garbage collection
                loaded_images.append(img_tk)

                # Create a frame for each image, its label, and checkbox
                image_frame = tk.Frame(image_panel_frame)
                image_frame.pack(side=tk.LEFT, padx=10, pady=10)

                # Display the image in the frame
                img_label = tk.Label(image_frame, image=img_tk)
                img_label.pack()

                # Create a variable to track the checkbox state
                checkbox_var = tk.BooleanVar()

                # Create a checkbox next to the image name and make it selectable
                checkbox = tk.Checkbutton(image_frame, text=f'{wavelength}_{i}', variable=checkbox_var,
                                          onvalue=True, offvalue=False,
                                          command=lambda idx=idx, var=checkbox_var: toggle_image_selection(idx, var))
                checkbox.pack(pady=5)

# Function to sum the cubes from the selected images
def sum_selected_cubes():
    if not selected_images:
        messagebox.showerror("Error", "No images selected for summing.")
        return

    combined_cube = None
    first_hdr_metadata = None
    rgb_bands = (29, 19, 9)  # Example of RGB bands

    for idx in selected_images:
        cube_data, cube_metadata, wavelength, i, _ = loaded_cubes[idx]

        logging.info(f"Summing cube for {wavelength}_{i}")

        # Sum the cubes
        if combined_cube is None:
            combined_cube = cube_data
            first_hdr_metadata = cube_metadata
        else:
            # Ensure the cubes have the same dimensions
            assert combined_cube.shape == cube_data.shape, "Cubes must have the same dimensions for summing."
            combined_cube += cube_data

    if combined_cube is not None:
        # Save the summed RGB image temporarily
        summed_rgb_image = os.path.join(saved_images_directory, 'summed_rgb_image.png')
        spy.save_rgb(summed_rgb_image, combined_cube, rgb_bands)
        logging.info(f"Summed RGB image saved at: {summed_rgb_image}")

        # Show the combined image in a popup window and provide Save options
        show_combined_image_popup(summed_rgb_image, combined_cube, first_hdr_metadata)
    else:
        messagebox.showerror("Error", "Could not sum the selected cubes.")

def save_rgb(image_path):
    # Ask the user to select a directory to save the RGB image
    directory = filedialog.askdirectory()
    if not directory:
        return  # No directory selected

    # Create the new file path
    rgb_save_path = os.path.join(directory, "summed_rgb_image.png")

    try:
        shutil.copy(image_path, rgb_save_path)
        messagebox.showinfo("Success", f"RGB image saved at: {rgb_save_path}")
    except Exception as e:
        logging.error(f"Failed to save RGB image: {e}")
        messagebox.showerror("Error", f"Failed to save RGB image: {e}")


# Function to save the summed hyperspectral cube
def save_cube(summed_cube, metadata):
    # Ask the user to select a directory to save the hyperspectral cube
    directory = filedialog.askdirectory()
    if not directory:
        return  # No directory selected

    hdr_save_path = os.path.join(directory, "summed_cube.hdr")
    bin_save_path = os.path.join(directory, "summed_cube.bin")

    try:
        # Save the hyperspectral cube using spectral.io.envi
        envi.save_image(hdr_save_path, summed_cube, metadata=metadata, force=True)
        messagebox.showinfo("Success", f"Summed cube saved at: {hdr_save_path}")
    except Exception as e:
        logging.error(f"Failed to save hyperspectral cube: {e}")
        messagebox.showerror("Error", f"Failed to save hyperspectral cube: {e}")
# Function to show the summed RGB image in a popup window
def show_combined_image_popup(image_path, summed_cube, metadata):
    popup = tk.Toplevel(root)
    popup.title("Summed Cube - RGB Image")

    # Load and display the RGB image in the popup window
    img = Image.open(image_path)
    img = img.resize((600, 400), Image.Resampling.LANCZOS)  # Resize for display
    img_tk = ImageTk.PhotoImage(img)

    img_label = tk.Label(popup, image=img_tk)
    img_label.image = img_tk  # Keep a reference to avoid garbage collection
    img_label.pack(pady=10)

    # Save RGB button
    save_rgb_button = tk.Button(popup, text="Save RGB", command=lambda: save_rgb(image_path))
    save_rgb_button.pack(side=tk.LEFT, padx=10)

    # Save Cube button
    save_cube_button = tk.Button(popup, text="Save Cube", command=lambda: save_cube(summed_cube, metadata))
    save_cube_button.pack(side=tk.LEFT, padx=10)

    popup.geometry("620x500")
    popup.transient(root)
    popup.grab_set()
    root.wait_window(popup)


# Set up the main application window
tls_found = False
golden_eye_found = False
tls_device_address = None
arduino_port = None
trigger_string = 'trigger\n'

root = tk.Tk()
root.title("WaveTrigger - Laboratory Equipment Control")
root.geometry("800x600")

# Create a notebook for tabs
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True)

# Create frames for each tab
acquisition_frame = tk.Frame(notebook)
processing_frame = tk.Frame(notebook)

# Add tabs to the notebook
notebook.add(acquisition_frame, text="Acquisition")
notebook.add(processing_frame, text="Processing")

# -------------------------------------------
# Acquisition Tab - Existing functionalities
# -------------------------------------------

columns = ("Wavelength", "Number of Pictures")
tree = ttk.Treeview(acquisition_frame, columns=columns, show="headings")
tree.heading("Wavelength", text="Wavelength (nm)")
tree.heading("Number of Pictures", text="Number of Pictures")
tree.pack(fill=tk.BOTH, expand=True)

device_frame = tk.Frame(acquisition_frame)
device_frame.pack(pady=10)

find_tls_button = tk.Button(device_frame, text="Find TLS", command=find_tls)
find_tls_button.pack(side=tk.LEFT, padx=10)

tls_status_label = tk.Label(device_frame, text="   ", bg='red', width=2)
tls_status_label.pack(side=tk.LEFT, padx=5)

find_golden_eye_button = tk.Button(device_frame, text="Find Golden Eye", command=find_golden_eye)
find_golden_eye_button.pack(side=tk.LEFT, padx=10)

golden_eye_status_label = tk.Label(device_frame, text="   ", bg='red', width=2)
golden_eye_status_label.pack(side=tk.LEFT, padx=5)

input_frame = tk.Frame(acquisition_frame)
input_frame.pack(fill=tk.X)

tk.Label(input_frame, text="Wavelength:").pack(side=tk.LEFT, padx=5, pady=5)
wavelength_entry = tk.Entry(input_frame)
wavelength_entry.pack(side=tk.LEFT, padx=5, pady=5)

tk.Label(input_frame, text="Number of Pictures:").pack(side=tk.LEFT, padx=5, pady=5)
pictures_entry = tk.Entry(input_frame)
pictures_entry.pack(side=tk.LEFT, padx=5, pady=5)

add_button = tk.Button(input_frame, text="Add Row", command=add_row)
add_button.pack(side=tk.LEFT, padx=5, pady=5)

execute_button = tk.Button(acquisition_frame, text="Execute Commands", command=execute_commands, state='disabled')
execute_button.pack(pady=10)

process_button = tk.Button(acquisition_frame, text="Process Results", command=process_results, state='disabled')
process_button.pack(pady=10)

# -------------------------------------------
# Processing Tab - New functionalities
# -------------------------------------------

# Filter Panel (Dropdown and Filter Button)
filter_panel = tk.Frame(processing_frame)
filter_panel.pack(pady=10, anchor='nw')

# Wavelength filter dropdown
tk.Label(filter_panel, text="Filter by Wavelength:").pack(side=tk.LEFT, padx=5)
wavelength_filter = ttk.Combobox(filter_panel, state="readonly")
wavelength_filter.pack(side=tk.LEFT, padx=5)

# Filter button
filter_button = tk.Button(filter_panel, text="Filter", command=filter_images)
filter_button.pack(side=tk.LEFT, padx=10)

load_folder_button = tk.Button(processing_frame, text="Load Folder", command=load_folder)
load_folder_button.pack(pady=10, anchor='nw')

# Progress Label to display how many subfolders have been loaded
progress_label = tk.Label(processing_frame, text="Loaded 0 of 0 subfolders")
progress_label.pack(pady=5, anchor='nw')

# Create a scrollable horizontal panel for displaying images
canvas = tk.Canvas(processing_frame)
canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

scrollbar = ttk.Scrollbar(processing_frame, orient=tk.HORIZONTAL, command=canvas.xview)
scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

# Frame inside the canvas where images will be displayed
image_panel_frame = tk.Frame(canvas)
canvas.create_window((0, 0), window=image_panel_frame, anchor="nw")
canvas.configure(xscrollcommand=scrollbar.set)

# Add a "Sum Cubes" button, initially disabled
sum_cubes_button = tk.Button(processing_frame, text="Sum Cubes", command=sum_selected_cubes, state="disabled")
sum_cubes_button.pack(pady=10)


# Function to resize the canvas when the number of images increases
def resize_canvas(event):
    canvas.configure(scrollregion=canvas.bbox("all"))


image_panel_frame.bind("<Configure>", resize_canvas)

# Run the application
root.mainloop()